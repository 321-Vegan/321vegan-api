from datetime import datetime
from typing import Optional
from sqlalchemy import or_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from app.log import get_logger
from app.crud.base import CRUDRepository
from app.models.restaurant import Restaurant
from app.models.restaurant_lock import RestaurantLock, RESTAURANT_LOCK_DURATION
from app.models.user import User

log = get_logger(__name__)


class RestaurantLockCRUDRepository(CRUDRepository):
    def get_live_lock(self, db: Session, restaurant: Restaurant) -> Optional[RestaurantLock]:
        """
        Get the validation lock of a restaurant, unless it's expired.

        Parameters:
            db (Session): The database session.
            restaurant (Restaurant): The locked restaurant.

        Returns:
            Optional[RestaurantLock]: The live lock, or None if the restaurant is free.
        """
        lock = db.query(RestaurantLock).filter(
            RestaurantLock.restaurant_id == restaurant.id
        ).populate_existing().first()
        if lock is None or lock.is_expired:
            return None
        return lock

    def lock(self, db: Session, restaurant: Restaurant, user: User) -> RestaurantLock:
        """
        Take or renew the validation lock of a restaurant. It's a single
        upsert so that two users can't both get it: an existing lock is only
        taken over if it's the user's own or expired.

        Parameters:
            db (Session): The database session.
            restaurant (Restaurant): The restaurant to lock.
            user (User): The user taking the lock.

        Returns:
            RestaurantLock: The restaurant lock after the attempt, held by
                another user if they have a live lock.
        """
        log.debug("locking restaurant %d for user %d", restaurant.id, user.id)
        now = datetime.now()
        stmt = insert(RestaurantLock).values(
            restaurant_id=restaurant.id, user_id=user.id, locked_at=now)
        stmt = stmt.on_conflict_do_update(
            index_elements=[RestaurantLock.restaurant_id],
            set_={"user_id": user.id, "locked_at": now},
            where=or_(
                RestaurantLock.user_id == user.id,
                RestaurantLock.locked_at < now - RESTAURANT_LOCK_DURATION,
            ),
        )
        db.execute(stmt)
        db.commit()
        return db.query(RestaurantLock).filter(
            RestaurantLock.restaurant_id == restaurant.id
        ).populate_existing().one()

    def unlock(self, db: Session, restaurant: Restaurant, user: User) -> None:
        """
        Release the validation lock of a restaurant, if the user holds it.

        Parameters:
            db (Session): The database session.
            restaurant (Restaurant): The restaurant to unlock.
            user (User): The user releasing the lock.
        """
        log.debug("unlocking restaurant %d for user %d", restaurant.id, user.id)
        db.query(RestaurantLock).filter(
            RestaurantLock.restaurant_id == restaurant.id,
            RestaurantLock.user_id == user.id,
        ).delete(synchronize_session=False)
        db.commit()


restaurant_lock_crud = RestaurantLockCRUDRepository(model=RestaurantLock)
