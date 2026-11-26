from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.models.notification import Notification
from app.models.notification_broadcast import NotificationBroadcast
from app.models.notification_delivery import NotificationDelivery
from app.models.push_device import PushDevice
from app.models.user import User
from app.services.notification import notification_service
from app.services.notification_delivery import notification_delivery_service


# Apps open an unknown type in their notification center, with no page
BROADCAST_TYPE = "announcement"

# Commit as it goes: each batch locks its users until the commit
BATCH_SIZE = 500


class NotificationBroadcastService:
    """Notifications sent to every account with pushes turned on."""

    def recipient_ids(self, db: Session) -> list[int]:
        """Active accounts with at least one device still taking pushes."""
        rows = (
            db.query(User.id)
            .join(PushDevice, PushDevice.user_id == User.id)
            .filter(User.is_active.is_(True), PushDevice.enabled.is_(True))
            .distinct()
            .order_by(User.id)
            .all()
        )
        return [user_id for (user_id,) in rows]

    def send(
        self,
        db: Session,
        *,
        title: str,
        body: str,
        sent_by_id: int | None,
    ) -> NotificationBroadcast:
        """One notification per recipient, queued for their devices (the FCM
        worker sends the pushes)."""
        user_ids = self.recipient_ids(db)
        broadcast = NotificationBroadcast(
            title=title,
            body=body,
            recipient_count=len(user_ids),
            sent_by_id=sent_by_id,
            created_at=datetime.now(),
        )
        db.add(broadcast)
        db.flush()

        for start in range(0, len(user_ids), BATCH_SIZE):
            batch = user_ids[start:start + BATCH_SIZE]
            # The lock NotificationService.create takes, for a whole batch:
            # each user's notification ids are committed in order
            db.query(User.id).filter(User.id.in_(batch)).order_by(
                User.id,
            ).with_for_update(key_share=True).all()
            now = datetime.now()
            expires_at = now + timedelta(days=notification_service.retention_days)
            notifications = [
                Notification(
                    user_id=user_id,
                    type=BROADCAST_TYPE,
                    title=title,
                    body=body,
                    payload={},
                    broadcast_id=broadcast.id,
                    created_at=now,
                    expires_at=expires_at,
                )
                for user_id in batch
            ]
            db.add_all(notifications)
            db.flush()
            notification_delivery_service.enqueue_for_notifications(
                db, notifications,
            )
            db.commit()

        db.commit()
        db.refresh(broadcast)
        return broadcast

    def list_with_stats(self, db: Session, limit: int = 50) -> list[dict]:
        """The last broadcasts, newest first, with how many were read and
        how the pushes went. Those counts drop to zero once the
        notifications are past their retention period."""
        broadcasts = (
            db.query(NotificationBroadcast)
            .options(joinedload(NotificationBroadcast.sent_by))
            .order_by(NotificationBroadcast.id.desc())
            .limit(limit)
            .all()
        )
        ids = [broadcast.id for broadcast in broadcasts]
        if not ids:
            return []

        read_counts = dict(
            db.query(Notification.broadcast_id, func.count(Notification.read_at))
            .filter(Notification.broadcast_id.in_(ids))
            .group_by(Notification.broadcast_id)
            .all()
        )
        pushes: dict[int, dict[str, int]] = {}
        rows = (
            db.query(
                Notification.broadcast_id,
                NotificationDelivery.status,
                func.count(NotificationDelivery.id),
            )
            .join(NotificationDelivery.notification)
            .filter(Notification.broadcast_id.in_(ids))
            .group_by(Notification.broadcast_id, NotificationDelivery.status)
            .all()
        )
        for broadcast_id, status, count in rows:
            pushes.setdefault(broadcast_id, {})[status] = count

        result = []
        for broadcast in broadcasts:
            statuses = pushes.get(broadcast.id, {})
            sent = statuses.get("sent", 0)
            failed = statuses.get("failed", 0)
            result.append({
                "id": broadcast.id,
                "title": broadcast.title,
                "body": broadcast.body,
                "recipient_count": broadcast.recipient_count,
                "sent_by": broadcast.sent_by.nickname if broadcast.sent_by else None,
                "created_at": broadcast.created_at,
                "read_count": read_counts.get(broadcast.id, 0),
                "pushes_sent": sent,
                "pushes_failed": failed,
                "pushes_pending": sum(statuses.values()) - sent - failed,
            })
        return result


notification_broadcast_service = NotificationBroadcastService()
