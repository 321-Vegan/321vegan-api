from typing import Optional, List, Tuple
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func, distinct
from app.crud.base import CRUDRepository
from app.models.shop import Shop
from app.models.scan_event import ScanEvent
from app.models.product_not_found_report import ProductNotFoundReport
from app.models.product_found_report import ProductFoundReport
from app.geo import haversine_distance, bounding_box_deltas


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
        lat_range, lon_range = bounding_box_deltas(latitude, radius_meters)

        # Find shops in the bounding box first (faster)
        shops = db.query(self._model).filter(
            self._model.latitude.between(latitude - lat_range, latitude + lat_range),
            self._model.longitude.between(longitude - lon_range, longitude + lon_range),
            self._model.date_deleted.is_(None)
        ).all()

        # Calculate exact distance
        for shop in shops:
            if haversine_distance(latitude, longitude, shop.latitude, shop.longitude) <= radius_meters:
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
        lat_range, lon_range = bounding_box_deltas(latitude, radius_meters)

        shops = db.query(self._model).filter(
            self._model.latitude.between(latitude - lat_range, latitude + lat_range),
            self._model.longitude.between(longitude - lon_range, longitude + lon_range),
            self._model.date_deleted.is_(None)
        ).all()

        shops_with_distance = []
        for shop in shops:
            distance = haversine_distance(
                latitude, longitude, shop.latitude, shop.longitude)

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
            self._model.date_deleted.is_(None)
        ).limit(limit).all()

    # A product seen without being scanned ("found" report) counts less than a
    # scan: its score starts lower and fades over a shorter, fixed window.
    SCAN_SCORE_CEILING = 0.99
    FOUND_REPORT_SCORE_CEILING = 0.70
    FOUND_REPORT_WINDOW_DAYS = 30

    def get_shop_scan_summary(
        self, db: Session, shop_id: int, include_reported: bool = False
    ) -> List[dict]:
        """
        Get the products seen at a shop with scan and report stats, and a
        computed presence score.

        A product is seen at a shop when it was scanned there, or reported as
        found there without a scan. Only not-found reports that occurred AFTER
        the last sighting for that EAN are considered relevant (a sighting
        after a report proves restocking).

        Parameters:
            db (Session): The database session.
            shop_id (int): The shop ID.
            include_reported (bool): Also return products that were only
                reported as found, never scanned at this shop. Off by default:
                older app versions expect a last scan date on every product.

        Returns:
            List[dict]: List of dicts with ean, scan_count, last_scanned_at
                        (None when never scanned), not_found_count,
                        last_not_found_at, found_count, last_found_at,
                        presence_score; most recently seen first.
        """
        scans = {
            row.ean: row
            for row in db.query(
                ScanEvent.ean,
                func.count(ScanEvent.id).label("count"),
                func.max(ScanEvent.created_at).label("last_at"),
            )
            .filter(ScanEvent.shop_id == shop_id)
            .group_by(ScanEvent.ean)
        }
        found_reports = {
            row.ean: row
            for row in db.query(
                ProductFoundReport.ean,
                func.count(ProductFoundReport.id).label("count"),
                func.max(ProductFoundReport.created_at).label("last_at"),
            )
            .filter(ProductFoundReport.shop_id == shop_id)
            .group_by(ProductFoundReport.ean)
        }
        not_found_dates: dict[str, list[datetime]] = {}
        for ean, created_at in db.query(
            ProductNotFoundReport.ean, ProductNotFoundReport.created_at
        ).filter(ProductNotFoundReport.shop_id == shop_id):
            not_found_dates.setdefault(ean, []).append(created_at)

        eans = set(scans)
        if include_reported:
            eans |= set(found_reports)

        now = datetime.now()
        summaries: list[tuple[datetime, dict]] = []

        for ean in eans:
            scan = scans.get(ean)
            found = found_reports.get(ean)
            last_scanned_at = scan.last_at if scan else None
            last_found_at = found.last_at if found else None

            # Only not-found reports made after the most recent sighting
            # (scan or found report) are still relevant.
            last_seen_at = max(d for d in (last_scanned_at, last_found_at) if d)
            relevant_report_dates = [
                d for d in not_found_dates.get(ean, []) if d > last_seen_at
            ]

            presence_score = self._compute_presence_score(
                now,
                last_scanned_at=last_scanned_at,
                scan_count=scan.count if scan else 0,
                last_found_at=last_found_at,
                report_dates=relevant_report_dates,
            )

            summaries.append((last_seen_at, {
                "ean": ean,
                "scan_count": scan.count if scan else 0,
                "last_scanned_at": last_scanned_at,
                "not_found_count": len(relevant_report_dates),
                "last_not_found_at": max(relevant_report_dates, default=None),
                "found_count": found.count if found else 0,
                "last_found_at": last_found_at,
                "presence_score": round(presence_score, 2),
            }))

        summaries.sort(key=lambda s: s[0], reverse=True)
        return [summary for _, summary in summaries]

    @classmethod
    def _compute_presence_score(
        cls,
        now: datetime,
        last_scanned_at: Optional[datetime],
        scan_count: int,
        last_found_at: Optional[datetime],
        report_dates: list[datetime],
    ) -> float:
        """
        Compute a presence score between 0.0 and 1.0.

        - A scan starts the score at 0.99. Frequency (scan count capped at 10)
          extends its decay window: 1 scan → 36 days, 10 scans → 90 days.
        - A found report (seen without a scan) starts it at 0.70 only, over a
          fixed 30-day window: it never weighs as much as a scan.
        - The score follows whichever of the two is higher.
        - Decay is quadratic (n=2): slow at first, accelerating over time.
        - Penalty: each not-found report made after the last sighting
          subtracts up to 0.25, decaying linearly over 30 days.
        - Floor: score never drops below 0.15 when no such report exists.
        """
        scan_score = 0.0
        if last_scanned_at is not None:
            frequency = max(0.0, min(1.0, scan_count / 10))
            scan_score = cls._freshness(
                now, last_scanned_at, 30 * (1 + frequency * 2)
            )

        found_score = 0.0
        if last_found_at is not None:
            found_score = cls.FOUND_REPORT_SCORE_CEILING * cls._freshness(
                now, last_found_at, cls.FOUND_REPORT_WINDOW_DAYS
            )

        penalty = 0.0
        for date in report_dates:
            days_ago = (now - date).total_seconds() / 86400
            penalty += 0.25 * max(0.0, 1.0 - days_ago / 30)

        min_score = 0.0 if report_dates else 0.15
        return max(
            min_score,
            min(cls.SCAN_SCORE_CEILING, max(scan_score, found_score) - penalty),
        )

    @staticmethod
    def _freshness(now: datetime, seen_at: datetime, window_days: float) -> float:
        """1.0 right after [seen_at], down to 0.0 after [window_days]."""
        days_since_seen = (now - seen_at).total_seconds() / 86400
        return max(0.0, 1.0 - (days_since_seen / window_days) ** 2)

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
