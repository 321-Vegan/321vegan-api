import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import firebase_admin
from firebase_admin import credentials, exceptions, messaging

from app.config import Settings, settings


class FCMConfigurationError(RuntimeError):
    """Raised when the FCM worker is enabled without valid configuration."""


@dataclass(frozen=True)
class FCMResult:
    success: bool
    status_code: int | None
    message_id: str | None = None
    reason: str | None = None
    retryable: bool = False
    invalid_device: bool = False


class FCMClient:
    """Firebase Admin client for cross-platform notification delivery."""

    APP_NAME = "321vegan-fcm"
    MAX_TTL = timedelta(days=28)

    def __init__(
        self,
        app_settings: Settings = settings,
        firebase_app: firebase_admin.App | None = None,
    ):
        self.settings = app_settings
        self._firebase_app = firebase_app
        self._owns_app = False

    def validate_configuration(self) -> None:
        if not self.settings.FIREBASE_PROJECT_ID:
            raise FCMConfigurationError("Missing FCM configuration: FIREBASE_PROJECT_ID")

        credential_path = self.settings.FIREBASE_CREDENTIALS_PATH
        if credential_path and not Path(credential_path).is_file():
            raise FCMConfigurationError(
                f"Firebase credentials not found at {credential_path}"
            )

    def initialize(self) -> None:
        self._app()

    def close(self) -> None:
        if self._firebase_app is not None and self._owns_app:
            firebase_admin.delete_app(self._firebase_app)
        self._firebase_app = None
        self._owns_app = False

    def send(
        self,
        *,
        registration_token: str,
        platform: str,
        title: str,
        body: str,
        notification_id: int,
        user_id: int,
        notification_type: str,
        data: dict[str, Any],
        expires_at: datetime,
    ) -> FCMResult:
        ttl = min(
            max(expires_at - datetime.now(), timedelta(0)),
            self.MAX_TTL,
        )
        message_data = {
            "notification_id": str(notification_id),
            "user_id": str(user_id),
            "type": notification_type,
            "data": json.dumps(data, ensure_ascii=False, separators=(",", ":")),
        }
        message = messaging.Message(
            token=registration_token,
            notification=messaging.Notification(title=title, body=body),
            data=message_data,
            android=self._android_config(ttl) if platform == "android" else None,
            apns=self._apns_config(expires_at) if platform == "ios" else None,
        )

        try:
            message_id = messaging.send(message, app=self._app())
            return FCMResult(
                success=True,
                status_code=200,
                message_id=message_id,
            )
        except (messaging.UnregisteredError, messaging.SenderIdMismatchError) as exc:
            return self._error_result(exc, invalid_device=True)
        except (
            messaging.QuotaExceededError,
            exceptions.DeadlineExceededError,
            exceptions.InternalError,
            exceptions.ResourceExhaustedError,
            exceptions.UnavailableError,
            exceptions.UnknownError,
        ) as exc:
            return self._error_result(exc, retryable=True)
        except (exceptions.FirebaseError, ValueError) as exc:
            return self._error_result(exc)

    def _app(self) -> firebase_admin.App:
        if self._firebase_app is not None:
            return self._firebase_app

        self.validate_configuration()
        try:
            self._firebase_app = firebase_admin.get_app(self.APP_NAME)
            return self._firebase_app
        except ValueError:
            pass

        credential = (
            credentials.Certificate(self.settings.FIREBASE_CREDENTIALS_PATH)
            if self.settings.FIREBASE_CREDENTIALS_PATH
            else credentials.ApplicationDefault()
        )
        self._firebase_app = firebase_admin.initialize_app(
            credential,
            # Device changes wait for an in-flight send; bound each HTTP wait.
            options={"projectId": self.settings.FIREBASE_PROJECT_ID, "httpTimeout": 15},
            name=self.APP_NAME,
        )
        self._owns_app = True
        return self._firebase_app

    def _android_config(self, ttl: timedelta) -> messaging.AndroidConfig:
        channel_id = self.settings.FCM_ANDROID_CHANNEL_ID or None
        return messaging.AndroidConfig(
            priority="high",
            ttl=ttl,
            notification=messaging.AndroidNotification(
                sound="default",
                channel_id=channel_id,
            ),
        )

    @staticmethod
    def _apns_config(expires_at: datetime) -> messaging.APNSConfig:
        return messaging.APNSConfig(
            headers={
                "apns-expiration": str(int(expires_at.timestamp())),
                "apns-priority": "10",
                "apns-push-type": "alert",
            },
            payload=messaging.APNSPayload(
                aps=messaging.Aps(sound="default"),
            ),
        )

    @staticmethod
    def _error_result(
        exc: Exception,
        *,
        retryable: bool = False,
        invalid_device: bool = False,
    ) -> FCMResult:
        response = getattr(exc, "http_response", None)
        status_code = getattr(response, "status_code", None)
        reason = getattr(exc, "code", None) or type(exc).__name__
        return FCMResult(
            success=False,
            status_code=status_code,
            reason=str(reason),
            retryable=retryable,
            invalid_device=invalid_device,
        )
