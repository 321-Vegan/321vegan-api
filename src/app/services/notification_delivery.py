from datetime import datetime, timedelta

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.log import get_logger
from app.models.notification import Notification
from app.models.notification_delivery import NotificationDelivery
from app.models.push_device import PushDevice
from app.services.fcm import FCMClient, FCMResult


log = get_logger(__name__)


class NotificationDeliveryService:
    """Queue and process per-device FCM deliveries."""

    def enqueue_for_notification(
        self,
        db: Session,
        notification: Notification,
    ) -> list[NotificationDelivery]:
        devices = (
            db.query(PushDevice)
            .filter(
                PushDevice.user_id == notification.user_id,
                PushDevice.enabled.is_(True),
            )
            .all()
        )
        now = datetime.now()
        deliveries = [
            NotificationDelivery(
                notification_id=notification.id,
                device_id=device.id,
                status="pending",
                attempt_count=0,
                next_attempt_at=now,
                created_at=now,
                updated_at=now,
            )
            for device in devices
        ]
        db.add_all(deliveries)
        return deliveries

    def _claim_next(
        self,
        db: Session,
        *,
        max_attempts: int,
        processing_timeout_seconds: int,
    ) -> tuple[int, int] | None:
        """Persist one attempt before sending; its number identifies the claim."""
        while True:
            now = datetime.now()
            stale_before = now - timedelta(seconds=processing_timeout_seconds)
            delivery = (
                db.query(NotificationDelivery)
                .join(Notification, Notification.id == NotificationDelivery.notification_id)
                .join(PushDevice, PushDevice.id == NotificationDelivery.device_id)
                .filter(
                    or_(
                        and_(
                            NotificationDelivery.status.in_(("pending", "retry")),
                            or_(
                                NotificationDelivery.next_attempt_at.is_(None),
                                NotificationDelivery.next_attempt_at <= now,
                            ),
                        ),
                        and_(
                            NotificationDelivery.status == "processing",
                            NotificationDelivery.last_attempt_at < stale_before,
                        ),
                    ),
                    Notification.expires_at > now,
                    PushDevice.enabled.is_(True),
                )
                .order_by(NotificationDelivery.next_attempt_at, NotificationDelivery.id)
                # An active send keeps this row locked even if its lease expires.
                # Do not lock joined devices here: send/logout lock device first.
                .with_for_update(of=NotificationDelivery, skip_locked=True)
                .populate_existing()
                .first()
            )
            if delivery is None:
                db.rollback()
                return None
            if delivery.attempt_count >= max_attempts:
                delivery.status = "failed"
                delivery.next_attempt_at = None
                delivery.last_error = "RetryLimitExceeded"
                delivery.updated_at = now
                db.commit()
                continue

            delivery.status = "processing"
            delivery.attempt_count += 1
            delivery.last_attempt_at = now
            delivery.updated_at = now
            claim = (delivery.id, delivery.attempt_count)
            db.commit()
            return claim

    def process_batch(
        self,
        db: Session,
        *,
        client: FCMClient,
        batch_size: int,
        max_attempts: int,
        processing_timeout_seconds: int,
    ) -> int:
        processed = 0
        try:
            for _ in range(batch_size):
                claim = self._claim_next(
                    db,
                    max_attempts=max_attempts,
                    processing_timeout_seconds=processing_timeout_seconds,
                )
                if claim is None:
                    break
                processed += self._deliver_claim(
                    db, client=client, claim=claim, max_attempts=max_attempts,
                )
        except Exception:
            db.rollback()
            raise
        return processed

    def _deliver_claim(
        self,
        db: Session,
        *,
        client: FCMClient,
        claim: tuple[int, int],
        max_attempts: int,
    ) -> bool:
        delivery_id, attempt_count = claim
        device = (
            db.query(PushDevice)
            .join(NotificationDelivery, NotificationDelivery.device_id == PushDevice.id)
            .filter(NotificationDelivery.id == delivery_id)
            .with_for_update(of=PushDevice)
            .populate_existing()
            .one_or_none()
        )
        delivery = (
            db.query(NotificationDelivery)
            .filter(
                NotificationDelivery.id == delivery_id,
                NotificationDelivery.status == "processing",
                NotificationDelivery.attempt_count == attempt_count,
            )
            .with_for_update()
            .populate_existing()
            .one_or_none()
        )
        if delivery is None or device is None:
            # Acknowledgement/expiry may have cascaded away this claimed delivery.
            db.rollback()
            return False

        notification = delivery.notification
        if not device.enabled or device.user_id != notification.user_id:
            reason = "DeviceOwnershipChangedOrDisabled"
        elif notification.expires_at <= datetime.now():
            reason = "NotificationExpired"
        elif notification.read_at is not None:
            reason = "NotificationRead"
        else:
            reason = None
        if reason:
            delivery.status = "failed"
            delivery.next_attempt_at = None
            delivery.last_error = reason
            delivery.updated_at = datetime.now()
            db.commit()
            return False

        # Keep both locks through the send and result commit. Logout/reassignment
        # must wait, and recovery workers skip this delivery even after timeout.
        try:
            result = client.send(
                registration_token=device.token,
                platform=device.platform,
                title=notification.title,
                body=notification.body,
                notification_id=notification.id,
                user_id=notification.user_id,
                notification_type=notification.type,
                data=notification.payload,
                expires_at=notification.expires_at,
            )
        except Exception as exc:
            # One unexpected transport failure must not strand the rest of the
            # batch. Log the error type, not credentials or destination tokens.
            log.error("FCM delivery %s failed: %s", delivery_id, type(exc).__name__)
            result = FCMResult(
                success=False, status_code=None, retryable=True,
                reason=f"Unexpected{type(exc).__name__}",
            )
        self._apply_result(delivery, device, result, max_attempts)
        db.commit()
        return True

    def _apply_result(
        self,
        delivery: NotificationDelivery,
        device: PushDevice,
        result: FCMResult,
        max_attempts: int,
    ) -> None:
        now = datetime.now()
        delivery.http_status = result.status_code
        delivery.provider_message_id = (
            result.message_id or delivery.provider_message_id
        )
        delivery.last_error = result.reason
        delivery.updated_at = now

        if result.success:
            delivery.status = "sent"
            delivery.sent_at = now
            delivery.next_attempt_at = None
            delivery.last_error = None
        elif result.invalid_device:
            delivery.status = "failed"
            delivery.next_attempt_at = None
            device.enabled = False
            device.invalidated_at = now
            device.updated_at = now
        elif result.retryable and delivery.attempt_count < max_attempts:
            delivery.status = "retry"
            delivery.next_attempt_at = now + self._retry_delay(
                result,
                delivery.attempt_count,
            )
        else:
            delivery.status = "failed"
            delivery.next_attempt_at = None

    @staticmethod
    def _retry_delay(result: FCMResult, attempt_count: int) -> timedelta:
        if result.reason in {"RESOURCE_EXHAUSTED", "QUOTA_EXCEEDED"}:
            return timedelta(minutes=15)
        if result.status_code is not None and result.status_code >= 500:
            return timedelta(minutes=15)
        return timedelta(seconds=min(60 * (2 ** (attempt_count - 1)), 15 * 60))


notification_delivery_service = NotificationDeliveryService()
