from datetime import datetime

from sqlalchemy.orm import Session

from app.crud.base import CRUDRepository
from app.models.notification import Notification


class NotificationCRUDRepository(CRUDRepository):
    def get_since(
        self,
        db: Session,
        user_id: int,
        after_id: int,
        limit: int,
        now: datetime | None = None,
    ) -> list[Notification]:
        """Return a user's non-expired notifications after a cursor."""
        current_time = now or datetime.now()
        return (
            db.query(self._model)
            .filter(
                self._model.user_id == user_id,
                self._model.id > after_id,
                self._model.expires_at > current_time,
            )
            .order_by(self._model.id.asc())
            .limit(limit)
            .all()
        )

    def mark_read_for_user(
        self,
        db: Session,
        notification_id: int,
        user_id: int,
    ) -> None:
        """Mark an owned notification read once; missing rows are harmless."""
        (
            db.query(self._model)
            .filter(
                self._model.id == notification_id,
                self._model.user_id == user_id,
                self._model.read_at.is_(None),
            )
            .update(
                {self._model.read_at: datetime.now()},
                synchronize_session=False,
            )
        )
        db.commit()

    def delete_for_user(
        self,
        db: Session,
        notification_id: int,
        user_id: int,
    ) -> None:
        """Delete an owned notification; missing rows are harmless."""
        (
            db.query(self._model)
            .filter(
                self._model.id == notification_id,
                self._model.user_id == user_id,
            )
            .delete(synchronize_session=False)
        )
        db.commit()

    def delete_expired(
        self,
        db: Session,
        now: datetime | None = None,
    ) -> int:
        """Delete expired notifications and return the affected row count."""
        current_time = now or datetime.now()
        return (
            db.query(self._model)
            .filter(self._model.expires_at <= current_time)
            .delete(synchronize_session=False)
        )


notification_crud = NotificationCRUDRepository(model=Notification)
