import argparse
import time

from app.config import settings
from app.database.session import SessionLocal
from app.log import get_logger
from app.services.fcm import FCMClient, FCMConfigurationError
from app.services.notification_delivery import notification_delivery_service


log = get_logger(__name__)


def process_once(client: FCMClient) -> int:
    db = SessionLocal()
    try:
        return notification_delivery_service.process_batch(
            db,
            client=client,
            batch_size=settings.FCM_BATCH_SIZE,
            max_attempts=settings.FCM_MAX_ATTEMPTS,
            processing_timeout_seconds=settings.FCM_PROCESSING_TIMEOUT_SECONDS,
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def run(*, once: bool = False) -> int:
    if not settings.FCM_ENABLED:
        log.info("FCM delivery is disabled; set FCM_ENABLED=true to run the worker")
        return 0

    client = FCMClient(settings)
    try:
        client.initialize()
    except (FCMConfigurationError, ValueError) as exc:
        log.error("FCM worker configuration error: %s", exc)
        return 1

    log.info("FCM worker started")
    try:
        while True:
            try:
                processed = process_once(client)
                if processed:
                    log.info("Processed %s FCM deliveries", processed)
            except Exception:
                log.exception("FCM delivery batch failed")
                if once:
                    return 1

            if once:
                return 0
            time.sleep(settings.FCM_POLL_INTERVAL_SECONDS)
    finally:
        client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process queued FCM deliveries")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process one batch and exit",
    )
    args = parser.parse_args()
    raise SystemExit(run(once=args.once))
