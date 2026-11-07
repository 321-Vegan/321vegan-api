from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.models.notification import Notification
from app.models.user import User
from app.services.notification_delivery import notification_delivery_service


class NotificationService:
    """Create durable notifications independently of their delivery channel."""

    def __init__(self, retention_days: int | None = None):
        self.retention_days = (
            retention_days
            if retention_days is not None
            else settings.NOTIFICATION_RETENTION_DAYS
        )

    def create(
        self,
        db: Session,
        *,
        user_id: int,
        notification_type: str,
        title: str,
        body: str,
        payload: dict[str, Any],
        commit: bool = True,
    ) -> Notification:
        """Create an occurrence, serializing inserts for each recipient until commit."""
        # Lock BEFORE allocating an ID. Otherwise a later ID could commit first
        # and an after_id cursor would permanently skip the earlier transaction.
        # NO KEY UPDATE also permits ordinary foreign-key checks on this user.
        db.query(User.id).filter(User.id == user_id).with_for_update(
            key_share=True,
        ).one()
        now = datetime.now()
        notification = Notification(
            user_id=user_id,
            type=notification_type,
            title=title,
            body=body,
            payload=payload,
            created_at=now,
            expires_at=now + timedelta(days=self.retention_days),
        )
        db.add(notification)
        db.flush()
        notification_delivery_service.enqueue_for_notification(db, notification)

        if commit:
            db.commit()
            db.refresh(notification)

        return notification


notification_service = NotificationService()
