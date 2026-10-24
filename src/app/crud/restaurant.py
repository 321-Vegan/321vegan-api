from typing import Optional, List, Tuple
from datetime import datetime, timezone
from sqlalchemy.orm import Session, noload
from sqlalchemy import func, or_
from app.crud.base import CRUDRepository
from app.crud.filters import buildQueryFilters
from app.geo import haversine_distance, bounding_box_deltas
from app.models.restaurant import Restaurant, RestaurantOperatingStatus
from app.models.restaurant_edit import RestaurantEdit
from app.models.restaurant_photo import RestaurantPhoto, RestaurantPhotoStatus
from app.models.restaurant_review import RestaurantReview, RestaurantReviewStatus


class RestaurantCRUDRepository(CRUDRepository):
    def get_by_id(self, db: Session, id: int) -> Optional[Restaurant]:
        """
        Retrieves a (non soft-deleted) restaurant by its ID.

        Parameters:
            db (Session): The database session.
            id (int): The restaurant ID.

        Returns:
            Optional[Restaurant]: The retrieved restaurant, if found and not deleted.
        """
        return db.query(self._model).filter(
            self._model.id == id,
            self._model.date_deleted.is_(None)
        ).first()

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
    ) -> Tuple[List[Restaurant], int]:
        """
        Override get_many to leave soft-deleted restaurants out by default.

        Parameters:
            db (Session): The database session.
            skip (int): Number of records to skip.
            limit (int): Maximum number of records to retrieve.
            order_by (str): Field name to order by.
            descending (bool): Sort direction.
            filters (dict): Filter parameters.

        Returns:
            Tuple[List[Restaurant], int]: List of restaurants and total count.
        """
        filters = filters or {}
        if 'date_deleted__isnull' not in filters:
            filters['date_deleted__isnull'] = True
        return super().get_many(
            db,
            *args,
            skip=skip,
            limit=limit,
            order_by=order_by,
            descending=descending,
            **filters,
            **kwargs
        )

    def create_for_user(self, db: Session, data: dict, user_id: int, validated: bool) -> Restaurant:
        """
        Create a restaurant submitted by a user.

        Parameters:
            db (Session): The database session.
            data (dict): The validated restaurant data.
            user_id (int): The ID of the user creating it.
            validated (bool): Whether it is visible to everyone right away.

        Returns:
            Restaurant: The created restaurant.
        """
        restaurant = self._model(
            **data, created_by=user_id, validated=validated)
        db.add(restaurant)
        db.commit()
        db.refresh(restaurant)
        return restaurant

    def update_with_history(
        self,
        db: Session,
        restaurant: Restaurant,
        values: dict,
        before: dict,
        after: dict,
        user_id: int,
        suggestion_id: Optional[int] = None,
    ) -> Restaurant:
        """
        Apply changes to a restaurant and record them in its history, in a
        single transaction. Validating it also approves the photos sent with it.

        Parameters:
            db (Session): The database session.
            restaurant (Restaurant): The restaurant to update.
            values (dict): The new values to set, by field.
            before (dict): JSON values of the changed fields before the change.
            after (dict): JSON values of the changed fields after the change.
            user_id (int): The author of the change.
            suggestion_id (Optional[int]): The suggestion it comes from, if any.

        Returns:
            Restaurant: The updated restaurant.
        """
        for field, value in values.items():
            setattr(restaurant, field, value)
        if after.get('validated') is True:
            for photo in restaurant.photos:
                if photo.review_id is None and photo.status == RestaurantPhotoStatus.PENDING:
                    photo.status = RestaurantPhotoStatus.APPROVED
        db.add(RestaurantEdit(
            restaurant_id=restaurant.id,
            user_id=user_id,
            suggestion_id=suggestion_id,
            before=before,
            after=after,
        ))
        db.commit()
        db.refresh(restaurant)
        return restaurant

    def soft_delete(self, db: Session, restaurant: Restaurant) -> Restaurant:
        """
        Soft-deletes a restaurant by setting its date_deleted timestamp, so
        its reviews and photos are preserved.

        Parameters:
            db (Session): The database session.
            restaurant (Restaurant): The restaurant to soft-delete.

        Returns:
            Restaurant: The soft-deleted restaurant.
        """
        restaurant.date_deleted = datetime.now(timezone.utc)
        db.add(restaurant)
        db.commit()
        db.refresh(restaurant)
        return restaurant

    def get_in_bounding_box(
        self,
        db: Session,
        min_lat: float,
        max_lat: float,
        min_lng: float,
        max_lng: float,
        user_id: int,
        filters: dict = None,
        limit: int = 300
    ) -> List[Tuple[Restaurant, Optional[float], Optional[int]]]:
        """
        Get the restaurants to show on the map within a bounding box, with
        their approved reviews stats: validated ones, plus the pending ones
        created by the user. Permanently closed ones are left out.

        Parameters:
            db (Session): The database session.
            min_lat (float): Minimum latitude.
            max_lat (float): Maximum latitude.
            min_lng (float): Minimum longitude.
            max_lng (float): Maximum longitude.
            user_id (int): The current user ID.
            filters (dict): Extra filter parameters (tags__overlap, vegan_status...).
            limit (int): Maximum number of restaurants to return (default 300).

        Returns:
            List[Tuple[Restaurant, Optional[float], Optional[int]]]:
                Restaurants with their average rating and review count.
        """
        stats = db.query(
            RestaurantReview.restaurant_id,
            func.avg(RestaurantReview.rating).label("rating_avg"),
            func.count(RestaurantReview.id).label("review_count"),
        ).filter(
            RestaurantReview.status == RestaurantReviewStatus.APPROVED
        ).group_by(RestaurantReview.restaurant_id).subquery()

        query = db.query(
            self._model, stats.c.rating_avg, stats.c.review_count
        ).outerjoin(
            stats, stats.c.restaurant_id == self._model.id
        ).options(
            noload(self._model.photos)
        ).filter(
            self._model.latitude.between(min_lat, max_lat),
            self._model.longitude.between(min_lng, max_lng),
            self._model.date_deleted.is_(None),
            self._model.operating_status != RestaurantOperatingStatus.PERMANENTLY_CLOSED,
            or_(self._model.validated.is_(True),
                self._model.created_by == user_id),
        )
        query = buildQueryFilters(self._model, query, filters or {})
        return query.limit(limit).all()

    def find_all_nearby(
        self,
        db: Session,
        latitude: float,
        longitude: float,
        radius_meters: int = 50
    ) -> List[Restaurant]:
        """
        Find all restaurants (validated or pending) within a given radius,
        sorted by distance (closest first). Used to spot duplicates.

        Parameters:
            db (Session): The database session.
            latitude (float): The latitude to search around.
            longitude (float): The longitude to search around.
            radius_meters (int): The search radius in meters (default 50).

        Returns:
            List[Restaurant]: Restaurants within radius sorted by distance.
        """
        lat_range, lon_range = bounding_box_deltas(latitude, radius_meters)

        restaurants = db.query(self._model).options(
            noload(self._model.photos)
        ).filter(
            self._model.latitude.between(
                latitude - lat_range, latitude + lat_range),
            self._model.longitude.between(
                longitude - lon_range, longitude + lon_range),
            self._model.date_deleted.is_(None)
        ).all()

        with_distance = []
        for restaurant in restaurants:
            distance = haversine_distance(
                latitude, longitude, restaurant.latitude, restaurant.longitude)
            if distance <= radius_meters:
                with_distance.append((distance, restaurant))

        with_distance.sort(key=lambda x: x[0])
        return [restaurant for _, restaurant in with_distance]

    def get_history(self, db: Session, restaurant_id: int) -> List[RestaurantEdit]:
        """
        Get the changes applied to a restaurant, newest first.

        Parameters:
            db (Session): The database session.
            restaurant_id (int): The restaurant ID.

        Returns:
            List[RestaurantEdit]: The restaurant history.
        """
        return db.query(RestaurantEdit).filter(
            RestaurantEdit.restaurant_id == restaurant_id
        ).order_by(RestaurantEdit.created_at.desc()).all()


class RestaurantPhotoCRUDRepository(CRUDRepository):
    def count_for_kind(self, db: Session, restaurant_id: int, kind: str) -> int:
        """
        Count the place or menu photos of a restaurant that were not rejected.

        Parameters:
            db (Session): The database session.
            restaurant_id (int): The restaurant ID.
            kind (str): The photo kind (PLACE or MENU).

        Returns:
            int: The number of photos.
        """
        return db.query(func.count(self._model.id)).filter(
            self._model.restaurant_id == restaurant_id,
            self._model.review_id.is_(None),
            self._model.kind == kind,
            self._model.status != RestaurantPhotoStatus.REJECTED,
        ).scalar() or 0


restaurant_crud = RestaurantCRUDRepository(model=Restaurant)
restaurant_photo_crud = RestaurantPhotoCRUDRepository(model=RestaurantPhoto)
