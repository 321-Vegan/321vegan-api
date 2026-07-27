from typing import Tuple
from sqlalchemy.orm import Session
from app.crud.base import CRUDRepository
from app.models.xp import XPActionType, XPEvent


class XPActionTypeCRUDRepository(CRUDRepository):
    def get_by_key(self, db: Session, key: str) -> XPActionType | None:
        """
        Get an XP action type by its stable key.

        Parameters:
            db (Session): The database session.
            key (str): The action type's key (e.g. "basic_scan").

        Returns:
            XPActionType | None: The action type, or None if not found.
        """
        return self.get_one(db, self._model.key == key)


class XPEventCRUDRepository(CRUDRepository):
    def get_by_user(
        self, db: Session, user_id: int, skip: int = 0, limit: int = 20
    ) -> Tuple[list[XPEvent], int]:
        """
        Get a user's XP events, most recent first, with pagination.

        Parameters:
            db (Session): The database session.
            user_id (int): The user ID.
            skip (int): Number of records to skip.
            limit (int): Maximum number of records to retrieve.

        Returns:
            Tuple[list[XPEvent], int]: The events and the total count.
        """
        query = db.query(self._model).filter(self._model.user_id == user_id)
        total = query.count()
        items = query.order_by(self._model.created_at.desc()) \
            .offset(skip).limit(limit).all()
        return items, total


xp_action_type_crud = XPActionTypeCRUDRepository(model=XPActionType)
xp_event_crud = XPEventCRUDRepository(model=XPEvent)
