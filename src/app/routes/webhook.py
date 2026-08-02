import base64
import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database.db import get_db
from app.log import get_logger
from app.schemas.subscription import AppleNotificationPayload, GooglePubSubPayload
from app.services.subscription_service import subscription_service

log = get_logger(__name__)

router = APIRouter()


@router.post("/apple", status_code=status.HTTP_200_OK)
async def apple_webhook(
    body: AppleNotificationPayload,
    db: Session = Depends(get_db),
):
    """
    Receive Apple App Store Server Notifications V2.
    Apple sends a signed JWS payload with subscription events.
    """
    try:
        success = subscription_service.process_apple_webhook(
            body.signedPayload, db)
        if not success:
            log.warning("Apple webhook processing returned failure")
        return {"status": "ok"}

    except Exception as e:
        # Unexpected/infra failure (e.g. DB pool timeout): return non-2xx so
        # Apple retries delivery instead of considering this notification
        # handled and dropping it for good.
        log.error(f"Apple webhook error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Temporary processing error",
        ) from e


@router.post("/google", status_code=status.HTTP_200_OK)
async def google_webhook(
    body: GooglePubSubPayload,
    db: Session = Depends(get_db),
):
    """
    Receive Google Real-Time Developer Notifications via Pub/Sub push.
    Google sends a Pub/Sub message with base64-encoded subscription data.
    """
    try:
        decoded = json.loads(base64.b64decode(
            body.message.data).decode("utf-8"))

        success = subscription_service.process_google_webhook(decoded, db)
        if not success:
            log.warning("Google webhook processing returned failure")
        return {"status": "ok"}

    except Exception as e:
        # Unexpected/infra failure: return non-2xx so Google retries
        # delivery instead of the event being silently dropped.
        log.error(f"Google webhook error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Temporary processing error",
        ) from e
