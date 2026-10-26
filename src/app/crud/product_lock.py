from datetime import datetime
from typing import Optional
from sqlalchemy import or_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from app.log import get_logger
from app.crud.base import CRUDRepository
from app.models.product import Product
from app.models.product_lock import ProductLock, PRODUCT_LOCK_DURATION
from app.models.user import User

log = get_logger(__name__)


class ProductLockCRUDRepository(CRUDRepository):
    def get_live_lock(self, db: Session, product: Product) -> Optional[ProductLock]:
        """
        Get the validation lock of a product, unless it's expired.

        Parameters:
            db (Session): The database session.
            product (Product): The locked product.

        Returns:
            Optional[ProductLock]: The live lock, or None if the product is free.
        """
        lock = db.query(ProductLock).filter(
            ProductLock.product_id == product.id
        ).populate_existing().first()
        if lock is None or lock.is_expired:
            return None
        return lock

    def lock(self, db: Session, product: Product, user: User) -> ProductLock:
        """
        Take or renew the validation lock of a product. It's a single upsert
        so that two users can't both get it: an existing lock is only taken
        over if it's the user's own or expired.

        Parameters:
            db (Session): The database session.
            product (Product): The product to lock.
            user (User): The user taking the lock.

        Returns:
            ProductLock: The product lock after the attempt, held by
                another user if they have a live lock.
        """
        log.debug("locking product %d for user %d", product.id, user.id)
        now = datetime.now()
        stmt = insert(ProductLock).values(
            product_id=product.id, user_id=user.id, locked_at=now)
        stmt = stmt.on_conflict_do_update(
            index_elements=[ProductLock.product_id],
            set_={"user_id": user.id, "locked_at": now},
            where=or_(
                ProductLock.user_id == user.id,
                ProductLock.locked_at < now - PRODUCT_LOCK_DURATION,
            ),
        )
        db.execute(stmt)
        db.commit()
        return db.query(ProductLock).filter(
            ProductLock.product_id == product.id
        ).populate_existing().one()

    def unlock(self, db: Session, product: Product, user: User) -> None:
        """
        Release the validation lock of a product, if the user holds it.

        Parameters:
            db (Session): The database session.
            product (Product): The product to unlock.
            user (User): The user releasing the lock.
        """
        log.debug("unlocking product %d for user %d", product.id, user.id)
        db.query(ProductLock).filter(
            ProductLock.product_id == product.id,
            ProductLock.user_id == user.id,
        ).delete(synchronize_session=False)
        db.commit()


product_lock_crud = ProductLockCRUDRepository(model=ProductLock)
