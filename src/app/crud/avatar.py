from typing import Optional, Tuple
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.crud.base import CRUDRepository
from app.models.avatar import Avatar, UserAvatar


class AvatarCRUDRepository(CRUDRepository):
    def get_by_key(self, db: Session, key: str) -> Optional[Avatar]:
        """
        Get an avatar by its stable key.

        Parameters:
            db (Session): The database session.
            key (str): The avatar's key (e.g. "cochon.png").

        Returns:
            Optional[Avatar]: The avatar, or None if not found.
        """
        return self.get_one(db, self._model.key == key)

    def get_pullable(self, db: Session) -> list[Avatar]:
        """
        Get the avatars eligible for a jeton pull: active, non-default.

        Parameters:
            db (Session): The database session.

        Returns:
            list[Avatar]: The pullable avatars.
        """
        return db.query(self._model).filter(
            self._model.is_active.is_(True),
            self._model.is_default.is_(False),
        ).all()


class UserAvatarCRUDRepository(CRUDRepository):
    def get_owned_avatar_ids(self, db: Session, user_id: int) -> set:
        """
        Get the set of avatar IDs a user has unlocked.

        Parameters:
            db (Session): The database session.
            user_id (int): The user ID.

        Returns:
            set: The IDs of avatars this user owns.
        """
        rows = db.query(self._model.avatar_id).filter(
            self._model.user_id == user_id).all()
        return {row.avatar_id for row in rows}

    def owns(self, db: Session, user_id: int, avatar_id: int) -> bool:
        """
        Whether a user owns a given avatar.

        Parameters:
            db (Session): The database session.
            user_id (int): The user ID.
            avatar_id (int): The avatar ID.

        Returns:
            bool: True if the user has unlocked this avatar.
        """
        return self.get_one(
            db,
            self._model.user_id == user_id,
            self._model.avatar_id == avatar_id,
        ) is not None

    def unlock(self, db: Session, user_id: int, avatar_id: int) -> Tuple[UserAvatar, bool]:
        """
        Record an avatar as owned by a user, if not already.

        Parameters:
            db (Session): The database session.
            user_id (int): The user ID.
            avatar_id (int): The avatar ID.

        Returns:
            Tuple[UserAvatar, bool]: The ownership row, and whether it
                was newly created (False if the user already owned it).
        """
        existing = self.get_one(
            db,
            self._model.user_id == user_id,
            self._model.avatar_id == avatar_id,
        )
        if existing:
            return existing, False
        row = self._model(user_id=user_id, avatar_id=avatar_id)
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            # Race condition — a concurrent pull for this same user
            # already recorded this avatar first.
            db.rollback()
            existing = self.get_one(
                db,
                self._model.user_id == user_id,
                self._model.avatar_id == avatar_id,
            )
            return existing, False
        db.refresh(row)
        return row, True


avatar_crud = AvatarCRUDRepository(model=Avatar)
user_avatar_crud = UserAvatarCRUDRepository(model=UserAvatar)
