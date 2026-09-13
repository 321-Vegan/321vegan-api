from typing import Optional, List, Tuple
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func, distinct
from app.crud.base import CRUDRepository
from app.models.shop import Shop
from app.models.scan_event import ScanEvent
from app.models.product_not_found_report import ProductNotFoundReport
from app.models.product_found_report import ProductFoundReport
import math


class ShopCRUDRepository(CRUDRepository):
    def get_by_id(self, db: Session, id: int) -> Optional[Shop]:
        """
        Retrieves a (non soft-deleted) shop by its ID.

        Parameters:
            db (Session): The database session.
            id (int): The shop ID.

        Returns:
            Optional[Shop]: The retrieved shop, if found and not deleted.
        """
        return db.query(self._model).filter(
            self._model.id == id,
            self._model.date_deleted.is_(None)
        ).first()

    def get_all(self, db: Session) -> List[Shop]:
        """
        Retrieves all non soft-deleted shops.

        Parameters:
            db (Session): The database session.

        Returns:
            List[Shop]: List of retrieved shops.
        """
        return db.query(self._model).filter(
            self._model.date_deleted.is_(None)
        ).all()

    def soft_delete(self, db: Session, shop: Shop) -> Shop:
        """
        Soft-deletes a shop by setting its date_deleted timestamp instead of
        removing the row, so its scan/review history is preserved.

        Parameters:
            db (Session): The database session.
            shop (Shop): The shop to soft-delete.

        Returns:
            Shop: The soft-deleted shop.
        """
        shop.date_deleted = datetime.now(timezone.utc)
        db.add(shop)
        db.commit()
        db.refresh(shop)
        return shop

    def get_many(
        self, 
        db: Session, 
        *args, 
        skip: int = 0, 
        limit: int = 100, 
        order_by: str = 'created_at', 
        descending: bool = False, 
        filters: dict = None,
        **kwargs
    ) -> Tuple[List[Shop], int]:
        """
        Override get_many to handle eans filter specially.
        
        Parameters:
            db (Session): The database session.
            skip (int): Number of records to skip.
            limit (int): Maximum number of records to retrieve.
            order_by (str): Field name to order by.
            descending (bool): Sort direction.
            filters (dict): Filter parameters.
            
        Returns:
            Tuple[List[Shop], int]: List of shops and total count.
        """
        filters = filters or {}
        if 'date_deleted__isnull' not in filters:
            filters['date_deleted__isnull'] = True

        eans = None
        if 'ean__in' in filters:
            eans = filters.pop('ean__in')

        if eans:
            shop_ids = self.get_shops_by_eans(db, eans)
            if not shop_ids:
                return [], 0
            filters = filters or {}
            filters['id__in'] = shop_ids
        
        return super().get_many(
            db,
            *args,
            skip=skip,
            limit=limit,
            order_by=order_by,
            descending=descending,
            **(filters or {}),
            **kwargs
        )
    
    def find_nearby(
        self, 
        db: Session, 
        latitude: float, 
        longitude: float, 
        radius_meters: int = 20
    ) -> Optional[Shop]:
        """
        Find a shop within a given radius using Haversine formula.
        
        Parameters:
            db (Session): The database session.
            latitude (float): The latitude to search around.
            longitude (float): The longitude to search around.
            radius_meters (int): The search radius in meters (default 20).
            
        Returns:
            Optional[Shop]: The nearest shop within radius, or None.
        """
        # Calculate distance using Haversine formula
        # https://en.wikipedia.org/wiki/Haversine_formula
        earth_radius = 6371000
        
        # Convert radius to degrees (approximate)
        lat_range = radius_meters / 111320 
        lon_range = radius_meters / (111320 * func.cos(func.radians(latitude)))
        
        # Find shops in the bounding box first (faster)
        shops = db.query(self._model).filter(
            self._model.latitude.between(latitude - lat_range, latitude + lat_range),
            self._model.longitude.between(longitude - lon_range, longitude + lon_range),
            self._model.date_deleted.is_(None)
        ).all()

        # Calculate exact distance
        for shop in shops:
            a = (math.sin(math.radians(shop.latitude - latitude) / 2) ** 2 +
                 math.cos(math.radians(latitude)) * math.cos(math.radians(shop.latitude)) *
                 math.sin(math.radians(shop.longitude - longitude) / 2) ** 2)
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            distance = earth_radius * c
            
            if distance <= radius_meters:
                return shop
        
        return None
    
    def find_all_nearby(
        self,
        db: Session,
        latitude: float,
        longitude: float,
        radius_meters: int = 100
    ) -> List[Shop]:
        """
        Find all shops within a given radius, sorted by distance (closest first).

        Parameters:
            db (Session): The database session.
            latitude (float): The latitude to search around.
            longitude (float): The longitude to search around.
            radius_meters (int): The search radius in meters (default 100).

        Returns:
            List[Shop]: Shops within radius sorted by distance.
        """
        earth_radius = 6371000

        lat_range = radius_meters / 111320
        lon_range = radius_meters / (111320 * func.cos(func.radians(latitude)))

        shops = db.query(self._model).filter(
            self._model.latitude.between(latitude - lat_range, latitude + lat_range),
            self._model.longitude.between(longitude - lon_range, longitude + lon_range),
            self._model.date_deleted.is_(None)
        ).all()

        shops_with_distance = []
        for shop in shops:
            a = (math.sin(math.radians(shop.latitude - latitude) / 2) ** 2 +
                 math.cos(math.radians(latitude)) * math.cos(math.radians(shop.latitude)) *
                 math.sin(math.radians(shop.longitude - longitude) / 2) ** 2)
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            distance = earth_radius * c

            if distance <= radius_meters:
                shops_with_distance.append((distance, shop))

        shops_with_distance.sort(key=lambda x: x[0])
        return [shop for _, shop in shops_with_distance]

    def get_by_osm_id(self, db: Session, osm_id: str) -> Optional[Shop]:
        """
        Get a shop by OpenStreetMap ID.
        
        Parameters:
            db (Session): The database session.
            osm_id (str): The OpenStreetMap ID.
            
        Returns:
            Optional[Shop]: The shop with the given OSM ID, or None.
        """
        return db.query(self._model).filter(
            self._model.osm_id == osm_id,
            self._model.date_deleted.is_(None)
        ).first()
    
    def get_in_bounding_box(
        self,
        db: Session,
        min_lat: float,
        max_lat: float,
        min_lng: float,
        max_lng: float,
        limit: int = 300
    ) -> List[Shop]:
        """
        Get shops within a geographic bounding box.

        Parameters:
            db (Session): The database session.
            min_lat (float): Minimum latitude.
            max_lat (float): Maximum latitude.
            min_lng (float): Minimum longitude.
            max_lng (float): Maximum longitude.
            limit (int): Maximum number of shops to return (default 300).

        Returns:
            List[Shop]: List of shops within the bounding box.
        """
        return db.query(self._model).filter(
            self._model.latitude.between(min_lat, max_lat),
            self._model.longitude.between(min_lng, max_lng),
            self._model.validated.is_(True),
            self._model.date_deleted.is_(None)
        ).limit(limit).all()

    def get_shop_scan_summary(self, db: Session, shop_id: int) -> List[dict]:
        """
        Get distinct EANs scanned at a shop with scan count, last scan date,
        not-found report stats, and a computed presence score.

        Only not-found reports that occurred AFTER the last scan for that EAN
        are considered relevant (a scan after a report proves restocking).

        Parameters:
            db (Session): The database session.
            shop_id (int): The shop ID.

        Returns:
            List[dict]: List of dicts with ean, scan_count, last_scanned_at,
                        not_found_count, last_not_found_at, presence_score.
        """
        from sqlalchemy import and_
        from sqlalchemy.dialects.postgresql import array_agg

        # Subquery 1: scan stats per EAN
        scan_subq = (
            db.query(
                ScanEvent.ean,
                func.count(ScanEvent.id).label("scan_count"),
                func.max(ScanEvent.created_at).label("last_scanned_at"),
            )
            .filter(ScanEvent.shop_id == shop_id)
            .group_by(ScanEvent.ean)
            .subquery()
        )

        # Subquery 2: not-found report stats per EAN, only reports after last scan
        report_subq = (
            db.query(
                ProductNotFoundReport.ean,
                func.count(ProductNotFoundReport.id).label("not_found_count"),
                func.max(ProductNotFoundReport.created_at).label("last_not_found_at"),
                array_agg(ProductNotFoundReport.created_at).label("report_dates"),
            )
            .join(
                scan_subq,
                and_(
                    scan_subq.c.ean == ProductNotFoundReport.ean,
                    ProductNotFoundReport.created_at > scan_subq.c.last_scanned_at,
                ),
            )
            .filter(ProductNotFoundReport.shop_id == shop_id)
            .group_by(ProductNotFoundReport.ean)
            .subquery()
        )

        # Subquery 3: found report stats per EAN, only reports after last scan
        found_subq = (
            db.query(
                ProductFoundReport.ean,
                func.count(ProductFoundReport.id).label("found_count"),
                func.max(ProductFoundReport.created_at).label("last_found_at"),
                array_agg(ProductFoundReport.created_at).label("found_dates"),
            )
            .join(
                scan_subq,
                and_(
                    scan_subq.c.ean == ProductFoundReport.ean,
                    ProductFoundReport.created_at > scan_subq.c.last_scanned_at,
                ),
            )
            .filter(ProductFoundReport.shop_id == shop_id)
            .group_by(ProductFoundReport.ean)
            .subquery()
        )

        # Join scan stats with report stats
        results = (
            db.query(
                scan_subq.c.ean,
                scan_subq.c.scan_count,
                scan_subq.c.last_scanned_at,
                func.coalesce(report_subq.c.not_found_count, 0).label("not_found_count"),
                report_subq.c.last_not_found_at,
                report_subq.c.report_dates,
                func.coalesce(found_subq.c.found_count, 0).label("found_count"),
                found_subq.c.last_found_at,
                found_subq.c.found_dates,
            )
            .outerjoin(report_subq, report_subq.c.ean == scan_subq.c.ean)
            .outerjoin(found_subq, found_subq.c.ean == scan_subq.c.ean)
            .order_by(scan_subq.c.last_scanned_at.desc())
            .all()
        )

        now = datetime.now()
        summaries = []

        for row in results:
            report_dates = [d for d in (row.report_dates or []) if d is not None]
            found_dates = [d for d in (row.found_dates or []) if d is not None]

            presence_score = self._compute_presence_score(
                now, row.last_scanned_at, row.scan_count, report_dates, found_dates,
            )

            summaries.append({
                "ean": row.ean,
                "scan_count": row.scan_count,
                "last_scanned_at": row.last_scanned_at,
                "not_found_count": row.not_found_count,
                "last_not_found_at": row.last_not_found_at,
                "found_count": row.found_count,
                "last_found_at": row.last_found_at,
                "presence_score": round(presence_score, 2),
            })

        return summaries

    @staticmethod
    def _compute_presence_score(
        now: datetime,
        last_scanned_at: datetime,
        scan_count: int,
        report_dates: list[datetime],
        found_dates: list[datetime],
    ) -> float:
        """
        Compute a presence score between 0.0 and 1.0.

        - Starts at 0.99 right after a scan.
        - Frequency (scan count capped at 10) extends the decay window:
          1 scan → 36-day window, 10 scans → 90-day window.
        - Decay is quadratic (n=2): slow at first, accelerating over time.
        - Penalty: each relevant not-found report subtracts up to 0.1,
          decaying linearly over 30 days.
        - Bonus: each relevant found report adds up to 0.6,
          decaying linearly over 30 days (counteracts not-found penalties).
        - Floor: score never drops below 0.1 when no not-found reports exist.
        """
        days_since_scan = (now - last_scanned_at).total_seconds() / 86400
        frequency = max(0.0, min(1.0, scan_count / 10))

        effective_window = 30 * (1 + frequency * 2)
        freshness = max(0.0, 1.0 - (days_since_scan / effective_window) ** 2)

        penalty = 0.0
        for date in report_dates:
            days_ago = (now - date).total_seconds() / 86400
            penalty += 0.1 * max(0.0, 1.0 - days_ago / 30)

        bonus = 0.0
        for date in found_dates:
            days_ago = (now - date).total_seconds() / 86400
            bonus += 0.6 * max(0.0, 1.0 - days_ago / 30)

        min_score = 0.0 if report_dates else 0.15
        return max(min_score, min(0.99, freshness - penalty + bonus))

    def get_shops_by_eans(self, db: Session, eans: List[str]) -> List[int]:
        """
        Get shop IDs that have products with the given EAN codes.
        
        Parameters:
            db (Session): The database session.
            eans (List[str]): List of EAN codes to search for.
            
        Returns:
            List[int]: List of shop IDs that have these products.
        """
        shop_ids = db.query(distinct(ScanEvent.shop_id)).filter(
            ScanEvent.shop_id.isnot(None),
            ScanEvent.ean.in_(eans)
        ).all()
        
        return [shop_id[0] for shop_id in shop_ids]


shop_crud = ShopCRUDRepository(model=Shop)
