import json
from datetime import datetime, timezone
from typing import Optional

from appstoreserverlibrary.api_client import AppStoreServerAPIClient
from appstoreserverlibrary.models.Environment import Environment
from appstoreserverlibrary.models.Status import Status as AppleStatus
from appstoreserverlibrary.signed_data_verifier import SignedDataVerifier
from google.oauth2 import service_account
from googleapiclient.discovery import build
from sqlalchemy.orm import Session

from app.config import settings
from app.crud.subscription import subscription_crud
from app.models.subscription import (
    Subscription,
    SubscriptionPlatform,
    SubscriptionStatus,
    SubscriptionEventType,
)
from app.log import get_logger

log = get_logger(__name__)

# Apple's per-subscription status (GetAllSubscriptionStatuses) mapped to ours.
APPLE_STATUS_MAP = {
    AppleStatus.ACTIVE: SubscriptionStatus.ACTIVE,
    AppleStatus.EXPIRED: SubscriptionStatus.EXPIRED,
    AppleStatus.BILLING_RETRY: SubscriptionStatus.GRACE_PERIOD,
    AppleStatus.BILLING_GRACE_PERIOD: SubscriptionStatus.GRACE_PERIOD,
    AppleStatus.REVOKED: SubscriptionStatus.CANCELLED,
}

# Google's subscriptionState (subscriptionsv2.get) mapped to ours. CANCELED
# means auto-renew is off but the subscriber keeps access until expiry, so it
# still maps to ACTIVE -- same semantics as Apple's DID_CHANGE_RENEWAL_STATUS.
GOOGLE_STATE_MAP = {
    "SUBSCRIPTION_STATE_ACTIVE": SubscriptionStatus.ACTIVE,
    "SUBSCRIPTION_STATE_CANCELED": SubscriptionStatus.ACTIVE,
    "SUBSCRIPTION_STATE_IN_GRACE_PERIOD": SubscriptionStatus.GRACE_PERIOD,
    "SUBSCRIPTION_STATE_ON_HOLD": SubscriptionStatus.GRACE_PERIOD,
    "SUBSCRIPTION_STATE_PAUSED": SubscriptionStatus.PAUSED,
    "SUBSCRIPTION_STATE_EXPIRED": SubscriptionStatus.EXPIRED,
}

# A drift in expires_at smaller than this is not worth flagging (clock/rounding noise).
DIAGNOSTICS_EXPIRY_DRIFT_TOLERANCE_SECONDS = 60


class SubscriptionService:
    """Service for handling in-app purchase subscription verification and webhooks."""

    # ──────────────────────────────────────────────
    # Apple App Store Server API v2
    # ──────────────────────────────────────────────

    def verify_apple_transaction(self, transaction_id: str) -> Optional[dict]:
        """
        Verify a transaction with Apple App Store Server API v2.
        Tries production first, falls back to sandbox if it fails.

        Returns decoded transaction info dict or None if invalid.
        """
        result = self._try_apple_verification(transaction_id, Environment.PRODUCTION)
        if result:
            return result

        log.info("Apple production verification failed, trying sandbox...")
        result = self._try_apple_verification(transaction_id, Environment.SANDBOX)
        if result:
            return result

        log.error(f"Apple transaction verification failed for both environments: transaction_id={transaction_id}")
        return None

    def _try_apple_verification(self, transaction_id: str, environment) -> Optional[dict]:
        """Attempt Apple transaction verification against a specific environment."""
        try:
            private_key = self._read_apple_private_key()
            if not private_key:
                log.error("Apple private key not configured")
                return None

            client = AppStoreServerAPIClient(
                signing_key=private_key,
                key_id=settings.APPLE_KEY_ID,
                issuer_id=settings.APPLE_ISSUER_ID,
                bundle_id=settings.APPLE_BUNDLE_ID,
                environment=environment,
            )

            transaction_info = client.get_transaction_info(transaction_id)

            root_certs = self._load_apple_root_certificates()
            verifier = SignedDataVerifier(
                root_certificates=root_certs,
                enable_online_checks=True,
                environment=environment,
                bundle_id=settings.APPLE_BUNDLE_ID,
                app_apple_id=settings.APPLE_APP_ID,
            )

            decoded = verifier.verify_and_decode_signed_transaction(
                transaction_info.signedTransactionInfo
            )

            return {
                "original_transaction_id": decoded.originalTransactionId,
                "transaction_id": decoded.transactionId,
                "product_id": decoded.productId,
                "expires_date": datetime.fromtimestamp(
                    decoded.expiresDate / 1000, tz=timezone.utc
                ) if decoded.expiresDate else None,
                "raw": {"signedTransactionInfo": transaction_info.signedTransactionInfo},
            }

        except Exception as e:
            log.warning(f"Apple verification failed ({environment}): {str(e)}")
            return None

    def process_apple_webhook(self, signed_payload: str, db: Session) -> bool:
        """
        Process an Apple App Store Server Notification V2.
        The payload is a signed JWS that we decode and verify.

        Returns False for a notification we understood but have nothing to
        do with (unverifiable signature, unknown subscription) — the caller
        should still ack these with 200, retrying wouldn't help. Raises on
        unexpected/infra failures (e.g. a DB timeout) so the caller can
        return a non-2xx and let Apple retry delivery instead of the event
        being silently dropped.
        """
        original_tx_id = None
        try:
            notification = None
            root_certs = self._load_apple_root_certificates()
            for environment in (Environment.PRODUCTION, Environment.SANDBOX):
                try:
                    verifier = SignedDataVerifier(
                        root_certificates=root_certs,
                        enable_online_checks=True,
                        environment=environment,
                        bundle_id=settings.APPLE_BUNDLE_ID,
                        app_apple_id=settings.APPLE_APP_ID,
                    )
                    notification = verifier.verify_and_decode_notification(signed_payload)
                    break
                except Exception:
                    continue

            if not notification:
                log.error("Apple webhook: could not verify notification in any environment")
                return False
            notification_type = notification.notificationType
            transaction_info = verifier.verify_and_decode_signed_transaction(
                notification.data.signedTransactionInfo
            )

            original_tx_id = transaction_info.originalTransactionId
            log.info(f"Apple webhook: processing {notification_type} for original_transaction_id={original_tx_id}")
            subscription = subscription_crud.get_by_original_transaction_id(db, original_tx_id)
            if not subscription:
                log.warning(f"Apple webhook: subscription not found for {original_tx_id}")
                return False

            # Idempotency: skip if we already processed this exact
            # notification delivery. Keyed on Apple's notificationUUID
            # (unique per delivery), not transactionId -- Apple reuses the
            # same transactionId across different notification types when
            # no new transaction occurred (e.g. EXPIRED carries the prior
            # DID_RENEW's transactionId), so keying on transactionId caused
            # those follow-up notifications to be misdetected as duplicates
            # and silently skipped, leaving status stuck at ACTIVE forever.
            incoming_notification_uuid = notification.notificationUUID
            if subscription.last_notification_uuid == incoming_notification_uuid:
                log.info(f"Apple webhook: already processed notification {incoming_notification_uuid}, skipping")
                return True

            event_type, new_status = self._map_apple_notification(
                notification_type, getattr(notification, "subtype", None)
            )

            if new_status:
                expires_at = None
                if transaction_info.expiresDate:
                    expires_at = datetime.fromtimestamp(
                        transaction_info.expiresDate / 1000, tz=timezone.utc
                    )
                subscription_crud.update_status(
                    db, subscription, new_status,
                    expires_at=expires_at,
                    transaction_id=transaction_info.transactionId,
                )

            if event_type:
                subscription_crud.create_event(
                    db, subscription.id, event_type,
                    platform_event_data={
                        "notification_type": notification_type,
                        "subtype": getattr(notification, "subtype", None),
                    },
                )

            subscription.last_notification_uuid = incoming_notification_uuid
            db.add(subscription)
            db.commit()

            return True

        except Exception as e:
            log.error(
                f"Apple webhook processing failed (original_transaction_id={original_tx_id}): {str(e)}"
            )
            raise

    # ──────────────────────────────────────────────
    # Google Play Developer API
    # ──────────────────────────────────────────────

    def verify_google_purchase(self, purchase_token: str, product_id: str) -> Optional[dict]:
        """
        Verify a subscription purchase with Google Play Developer API.
        Uses google-api-python-client with a service account.

        Returns subscription info dict or None if invalid.
        """
        try:
            credentials = service_account.Credentials.from_service_account_file(
                settings.GOOGLE_SERVICE_ACCOUNT_PATH,
                scopes=["https://www.googleapis.com/auth/androidpublisher"],
            )

            service = build("androidpublisher", "v3", credentials=credentials)

            result = service.purchases().subscriptionsv2().get(
                packageName=settings.GOOGLE_PLAY_PACKAGE_NAME,
                token=purchase_token,
            ).execute()

            # Extract the latest line item for expiry info
            line_items = result.get("lineItems", [])
            expiry_time = None
            if line_items:
                expiry_str = line_items[0].get("expiryTime")
                if expiry_str:
                    expiry_time = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))

            return {
                "original_transaction_id": result.get("linkedPurchaseToken", purchase_token),
                "purchase_token": purchase_token,
                "product_id": product_id,
                "expires_date": expiry_time,
                "subscription_state": result.get("subscriptionState"),
                "raw": result,
            }

        except Exception as e:
            log.error(f"Google purchase verification failed: {str(e)}")
            return None

    def process_google_webhook(self, message_data: dict, db: Session) -> bool:
        """
        Process a Google Real-Time Developer Notification.
        message_data is the decoded Pub/Sub message data.

        Returns False for a notification we understood but have nothing to
        do with (no purchase token, unknown subscription) — the caller
        should still ack these with 200. Raises on unexpected/infra
        failures so the caller can return a non-2xx and let Google retry
        instead of the event being silently dropped.
        """
        original_tx_id = None
        try:
            notification = message_data.get("subscriptionNotification")
            if not notification:
                log.warning("Google webhook: no subscriptionNotification in payload")
                return False

            purchase_token = notification.get("purchaseToken")
            notification_type = notification.get("notificationType")

            # Call Google API to get current subscription state
            product_id = notification.get("subscriptionId", "")
            verified = self.verify_google_purchase(purchase_token, product_id)
            if not verified:
                log.error("Google webhook: could not verify purchase token")
                return False

            original_tx_id = verified["original_transaction_id"]
            log.info(f"Google webhook: processing notification_type={notification_type} for original_transaction_id={original_tx_id}")
            subscription = subscription_crud.get_by_original_transaction_id(db, original_tx_id)
            if not subscription:
                log.warning(f"Google webhook: subscription not found for {original_tx_id}")
                return False

            event_type, new_status = self._map_google_notification(notification_type)

            if new_status:
                subscription_crud.update_status(
                    db, subscription, new_status,
                    expires_at=verified.get("expires_date"),
                )

            if event_type:
                subscription_crud.create_event(
                    db, subscription.id, event_type,
                    platform_event_data={"notification_type": notification_type, "raw": verified.get("raw")},
                )

            return True

        except Exception as e:
            log.error(
                f"Google webhook processing failed (original_transaction_id={original_tx_id}): {str(e)}"
            )
            raise

    # ──────────────────────────────────────────────
    # Shared verification flow
    # ──────────────────────────────────────────────

    def process_verification(
        self,
        db: Session,
        user_id: int,
        platform: str,
        transaction_id: Optional[str],
        purchase_token: Optional[str],
        product_id: str,
    ) -> Optional[Subscription]:
        """
        Main verification flow called from the /subscriptions/verify endpoint.
        Validates with Apple/Google, upserts subscription, logs event, grants badge.
        """
        if platform == SubscriptionPlatform.APPLE:
            if not transaction_id:
                log.error("Apple verification requires transaction_id")
                return None
            verified = self.verify_apple_transaction(transaction_id)
        elif platform == SubscriptionPlatform.GOOGLE:
            if not purchase_token:
                log.error("Google verification requires purchase_token")
                return None
            verified = self.verify_google_purchase(purchase_token, product_id)
        else:
            log.error(f"Unknown platform: {platform}")
            return None

        if not verified:
            log.error(
                f"Verification failed for user_id={user_id}, platform={platform}, "
                f"transaction_id={transaction_id}, purchase_token={purchase_token}"
            )
            return None

        original_tx_id = verified["original_transaction_id"]

        # Update subscription
        subscription = subscription_crud.get_by_original_transaction_id(db, original_tx_id)
        if subscription:
            subscription_crud.update_status(
                db, subscription, SubscriptionStatus.ACTIVE,
                expires_at=verified.get("expires_date"),
                transaction_id=verified.get("transaction_id"),
            )
            event_type = SubscriptionEventType.RENEWAL
        else:
            subscription = Subscription(
                user_id=user_id,
                platform=platform,
                original_transaction_id=original_tx_id,
                transaction_id=verified.get("transaction_id"),
                purchase_token=verified.get("purchase_token"),
                product_id=verified.get("product_id", product_id),
                status=SubscriptionStatus.ACTIVE,
                expires_at=verified.get("expires_date"),
            )
            db.add(subscription)
            db.commit()
            db.refresh(subscription)
            event_type = SubscriptionEventType.INITIAL_PURCHASE

        # Log event
        subscription_crud.create_event(
            db, subscription.id, event_type,
            platform_event_data=verified.get("raw"),
        )

        # Grant permanent supporter badge
        subscription_crud.grant_supporter_badge(db, user_id)

        log.info(
            f"Verification succeeded for user_id={user_id}, subscription_id={subscription.id}, "
            f"platform={platform}, status={subscription.status}, expires_at={subscription.expires_at}"
        )
        return subscription

    # ──────────────────────────────────────────────
    # Diagnostics (admin)
    # ──────────────────────────────────────────────

    def run_subscription_diagnostics(
        self, db: Session,
        platform: Optional[SubscriptionPlatform] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> list[dict]:
        """
        Compare active/grace_period subscriptions against the platform's
        live, authoritative status and report drift. Read-only -- does not
        write any corrections, just reports.

        One external API call per subscription, so this is meant to be
        triggered on demand by an admin, not run on a hot path or scheduled
        at high frequency. Pass `platform` and/or `limit`/`offset` to page
        through in batches at real subscriber counts -- unfiltered, a full
        run can take minutes and risk the request itself timing out.
        Ordered by id so limit/offset paging is stable across calls.

        Limitation: Apple's and Google's APIs only let us look up a
        purchase we already know the identifier for. A purchase that
        exists on their side but was never recorded in our DB at all (e.g.
        a missed initial notification with no matching /verify call) is
        invisible to this check.
        """
        query = db.query(Subscription).filter(
            Subscription.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.GRACE_PERIOD])
        ).order_by(Subscription.id)
        if platform is not None:
            query = query.filter(Subscription.platform == platform)
        if offset is not None:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        candidates = query.all()

        # Release the DB connection back to the pool before the external
        # API loop below: everything we need from `candidates` is already
        # loaded, and each iteration can take a while (Apple verification
        # includes an online OCSP check)
        db.close()

        issues = []
        for sub in candidates:
            if sub.platform == SubscriptionPlatform.APPLE:
                live = self._get_apple_live_status(sub.original_transaction_id)
            elif sub.platform == SubscriptionPlatform.GOOGLE:
                if not sub.purchase_token:
                    issues.append(self._diagnostic_issue(sub, "missing_purchase_token"))
                    continue
                live = self._get_google_live_status(sub.purchase_token, sub.product_id)
            else:
                continue

            if live is None:
                issues.append(self._diagnostic_issue(sub, "could_not_verify"))
                continue

            status_drift = live["status"] is not None and live["status"] != sub.status
            expiry_drift = (
                live["expires_at"] is not None and sub.expires_at is not None and
                abs((live["expires_at"].replace(tzinfo=None) - sub.expires_at).total_seconds())
                > DIAGNOSTICS_EXPIRY_DRIFT_TOLERANCE_SECONDS
            )

            if status_drift or expiry_drift:
                issues.append(self._diagnostic_issue(
                    sub,
                    "status_drift" if status_drift else "expiry_drift",
                    live_status=live["status"].value if live["status"] else live["raw_status"],
                    live_expires_at=live["expires_at"],
                ))

        return issues

    @staticmethod
    def _diagnostic_issue(
        sub: Subscription, issue: str,
        live_status: Optional[str] = None, live_expires_at: Optional[datetime] = None,
    ) -> dict:
        return {
            "subscription_id": sub.id,
            "user_id": sub.user_id,
            "platform": sub.platform.value,
            "original_transaction_id": sub.original_transaction_id,
            "issue": issue,
            "local_status": sub.status.value,
            "local_expires_at": sub.expires_at.isoformat() if sub.expires_at else None,
            "live_status": live_status,
            "live_expires_at": live_expires_at.isoformat() if live_expires_at else None,
        }

    def _get_apple_live_status(self, original_transaction_id: str) -> Optional[dict]:
        """Apple's current status for one subscription, trying PRODUCTION then SANDBOX."""
        private_key = self._read_apple_private_key()
        if not private_key:
            return None
        root_certs = self._load_apple_root_certificates()

        for environment in (Environment.PRODUCTION, Environment.SANDBOX):
            try:
                client = AppStoreServerAPIClient(
                    signing_key=private_key,
                    key_id=settings.APPLE_KEY_ID,
                    issuer_id=settings.APPLE_ISSUER_ID,
                    bundle_id=settings.APPLE_BUNDLE_ID,
                    environment=environment,
                )
                response = client.get_all_subscription_statuses(original_transaction_id)
            except Exception as e:
                log.debug(f"get_all_subscription_statuses failed on {environment}: {e}")
                continue

            verifier = SignedDataVerifier(
                root_certificates=root_certs,
                enable_online_checks=True,
                environment=environment,
                bundle_id=settings.APPLE_BUNDLE_ID,
                app_apple_id=settings.APPLE_APP_ID,
            )

            for group in response.data or []:
                for item in group.lastTransactions or []:
                    if item.originalTransactionId != original_transaction_id:
                        continue
                    try:
                        decoded = verifier.verify_and_decode_signed_transaction(item.signedTransactionInfo)
                    except Exception as e:
                        log.debug(f"could not decode transaction for {original_transaction_id}: {e}")
                        continue
                    expires_at = (
                        datetime.fromtimestamp(decoded.expiresDate / 1000, tz=timezone.utc)
                        if decoded.expiresDate else None
                    )
                    return {
                        "status": APPLE_STATUS_MAP.get(item.status),
                        "raw_status": item.status.name if item.status else None,
                        "expires_at": expires_at,
                    }
        return None

    def _get_google_live_status(self, purchase_token: str, product_id: str) -> Optional[dict]:
        verified = self.verify_google_purchase(purchase_token, product_id)
        if not verified:
            return None
        raw_state = verified.get("subscription_state")
        return {
            "status": GOOGLE_STATE_MAP.get(raw_state),
            "raw_status": raw_state,
            "expires_at": verified.get("expires_date"),
        }

    # ──────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────

    def _read_apple_private_key(self) -> Optional[bytes]:
        try:
            with open(settings.APPLE_PRIVATE_KEY_PATH, "rb") as f:
                return f.read()
        except Exception as e:
            log.error(f"Could not read Apple private key: {str(e)}")
            return None

    def _load_apple_root_certificates(self) -> list[bytes]:
        try:
            with open(settings.APPLE_ROOT_CA_CERT_PATH, "rb") as f:
                return [f.read()]
        except Exception as e:
            log.error(f"Could not read Apple root CA certificate: {str(e)}")
            return []

    @staticmethod
    def _map_apple_notification(
        notification_type: str, subtype: Optional[str] = None
    ) -> tuple[Optional[SubscriptionEventType], Optional[SubscriptionStatus]]:
        """Map Apple notification type to our event type and subscription status."""
        # Handle DID_CHANGE_RENEWAL_STATUS subtypes
        if notification_type == "DID_CHANGE_RENEWAL_STATUS":
            if subtype == "AUTO_RENEW_ENABLED":
                return (SubscriptionEventType.RENEWAL, None)
            elif subtype == "AUTO_RENEW_DISABLED":
                return (SubscriptionEventType.CANCELLATION, None)
            return (None, None)

        mapping = {
            "DID_RENEW": (SubscriptionEventType.RENEWAL, SubscriptionStatus.ACTIVE),
            "EXPIRED": (SubscriptionEventType.EXPIRY, SubscriptionStatus.EXPIRED),
            "GRACE_PERIOD_EXPIRED": (SubscriptionEventType.EXPIRY, SubscriptionStatus.EXPIRED),
            "DID_FAIL_TO_RENEW": (SubscriptionEventType.GRACE_PERIOD, SubscriptionStatus.GRACE_PERIOD),
            "REFUND": (SubscriptionEventType.REFUND, SubscriptionStatus.CANCELLED),
            "SUBSCRIBED": (SubscriptionEventType.INITIAL_PURCHASE, SubscriptionStatus.ACTIVE),
        }
        return mapping.get(notification_type, (None, None))

    @staticmethod
    def _map_google_notification(notification_type: int) -> tuple[Optional[SubscriptionEventType], Optional[SubscriptionStatus]]:
        """Map Google RTDN notification type (int) to our event type and subscription status."""
        # Google notification types: https://developer.android.com/google/play/billing/rtdn-reference
        mapping = {
            1: (SubscriptionEventType.RENEWAL, SubscriptionStatus.ACTIVE),           # SUBSCRIPTION_RECOVERED
            2: (SubscriptionEventType.RENEWAL, SubscriptionStatus.ACTIVE),           # SUBSCRIPTION_RENEWED
            3: (SubscriptionEventType.CANCELLATION, None),                           # SUBSCRIPTION_CANCELED (still active until period end)
            4: (SubscriptionEventType.INITIAL_PURCHASE, SubscriptionStatus.ACTIVE),  # SUBSCRIPTION_PURCHASED
            5: (SubscriptionEventType.GRACE_PERIOD, SubscriptionStatus.GRACE_PERIOD),# SUBSCRIPTION_ON_HOLD
            6: (SubscriptionEventType.GRACE_PERIOD, SubscriptionStatus.GRACE_PERIOD),# SUBSCRIPTION_IN_GRACE_PERIOD
            7: (SubscriptionEventType.RENEWAL, SubscriptionStatus.ACTIVE),           # SUBSCRIPTION_RESTARTED
            10: (SubscriptionEventType.PAUSED, SubscriptionStatus.PAUSED),            # SUBSCRIPTION_PAUSED
            11: (SubscriptionEventType.PAUSED, None),                               # SUBSCRIPTION_PAUSE_SCHEDULE_CHANGED
            12: (SubscriptionEventType.REFUND, SubscriptionStatus.CANCELLED),        # SUBSCRIPTION_REVOKED
            13: (SubscriptionEventType.EXPIRY, SubscriptionStatus.EXPIRED),          # SUBSCRIPTION_EXPIRED
        }
        return mapping.get(notification_type, (None, None))


subscription_service = SubscriptionService()
