from typing import Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.crud.base import CRUDRepository
from app.models.scan_event import ScanEvent


class ScanEventCRUDRepository(CRUDRepository):
    def get_by_ean(self, db: Session, ean: str, limit: int = 100) -> list[ScanEvent]:
        """
        Get scan events by EAN.

        Parameters:
            db (Session): The database session.
            ean (str): The EAN of the product.
            limit (int): Maximum number of results to return.

        Returns:
            list[ScanEvent]: List of scan events for the given EAN.
        """
        return db.query(self._model).filter(
            self._model.ean == ean
        ).order_by(self._model.created_at.desc()).limit(limit).all()
    
    def get_user_scan_summary(self, db: Session, user_id: int) -> list[dict]:
        """
        Get aggregated scan statistics for a user.
        Returns EANs with their scan counts.

        Parameters:
            db (Session): The database session.
            user_id (int): The user ID.

        Returns:
            list[dict]: List of {ean: str, scan_count: int} ordered by scan count desc.
        """
        result = db.query(
            self._model.ean,
            func.count(self._model.id).label('scan_count')
        ).filter(
            self._model.user_id == user_id
        ).group_by(
            self._model.ean
        ).order_by(
            func.count(self._model.id).desc()
        ).all()
        
        return [{"ean": row.ean, "scan_count": row.scan_count} for row in result]

    def ean_already_found_at_shop(
        self, db: Session, ean: str, shop_id: int, exclude_event_id: int
    ) -> bool:
        """
        Whether any user has already scanned `ean` at `shop_id` before,
        other than `exclude_event_id` (the scan currently being
        processed). Global across users — used for the "first to find
        this product in this shop" community bonus, not a per-user check.

        Parameters:
            db (Session): The database session.
            ean (str): The product EAN.
            shop_id (int): The shop ID.
            exclude_event_id (int): The scan event to exclude (the one
                just created for this scan).

        Returns:
            bool: True if another scan of this product at this shop
                already exists.
        """
        return db.query(self._model.id).filter(
            self._model.ean == ean,
            self._model.shop_id == shop_id,
            self._model.id != exclude_event_id,
        ).first() is not None


scan_event_crud = ScanEventCRUDRepository(model=ScanEvent)
