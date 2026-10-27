from collections import defaultdict
from typing import Dict, Optional, List, Tuple
from datetime import datetime, timezone
from sqlalchemy.orm import Session, noload
from sqlalchemy import and_, func, or_
from app.crud.base import CRUDRepository
from app.crud.filters import buildQueryFilters
from app.geo import haversine_distance, bounding_box_deltas
from app.models.restaurant import Restaurant, RestaurantOperatingStatus, RestaurantVeganStatus
from app.models.restaurant_edit import RestaurantEdit
from app.models.restaurant_photo import RestaurantPhoto, RestaurantPhotoKind, RestaurantPhotoStatus, pick_featured_photo
from app.models.restaurant_review import RestaurantReview, RestaurantReviewStatus
from app.models.restaurant_save import RestaurantSave

# Apostrophes vary with the keyboard (iOS types ’) and the source of the
# name: the search takes them all as '
APOSTROPHES = "\u2019\u2018\u02bc`\u00b4"


def without_apostrophe_variants(column):
    """The column with its apostrophes as ', to compare with search_pattern."""
    return func.translate(column, APOSTROPHES, "'" * len(APOSTROPHES))


def search_pattern(text: str) -> str:
    """
    A searched text ready for an ILIKE with escape='\\': apostrophes as ',
    and the LIKE wildcards in it taken literally.
    """
    return text.strip().translate(
        str.maketrans(APOSTROPHES, "'" * len(APOSTROPHES))).replace(
        '\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


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

    def get_created_by(
        self,
        db: Session,
        user_id: int,
        skip: int = 0,
        limit: int = 20
    ) -> Tuple[List[Restaurant], int]:
        """
        Get the restaurants created by a user, newest first: pending,
        validated, and the ones refused (deleted while pending), so the user
        learns why.

        Parameters:
            db (Session): The database session.
            user_id (int): The user ID.
            skip (int): Number of records to skip.
            limit (int): Maximum number of records to retrieve.

        Returns:
            Tuple[List[Restaurant], int]: The restaurants and total count.
        """
        query = db.query(self._model).filter(
            self._model.created_by == user_id,
            or_(self._model.date_deleted.is_(None),
                self._model.validated.is_(False)),
        )
        total = query.count()
        restaurants = query.order_by(
            self._model.created_at.desc()).offset(skip).limit(limit).all()
        return restaurants, total

    def soft_delete(
        self,
        db: Session,
        restaurant: Restaurant,
        rejection_reason: Optional[str] = None,
    ) -> Restaurant:
        """
        Soft-deletes a restaurant by setting its date_deleted timestamp, so
        its reviews and photos are preserved.

        Parameters:
            db (Session): The database session.
            restaurant (Restaurant): The restaurant to soft-delete.
            rejection_reason (Optional[str]): Why it was refused, when pending.

        Returns:
            Restaurant: The soft-deleted restaurant.
        """
        restaurant.date_deleted = datetime.now(timezone.utc)
        restaurant.rejection_reason = rejection_reason
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
        max_plant_milk_surcharge: Optional[float] = None,
        limit: int = 300
    ) -> List[Tuple[Restaurant, Optional[float], Optional[int]]]:
        """
        Get the restaurants to show on the map within a bounding box, with
        their approved reviews stats: validated ones, plus the pending ones
        created by the user. Food trucks are kept when any of their stops is
        in the box. Permanently closed ones are kept, so the app can show
        users they closed.

        Parameters:
            db (Session): The database session.
            min_lat (float): Minimum latitude.
            max_lat (float): Maximum latitude.
            min_lng (float): Minimum longitude.
            max_lng (float): Maximum longitude.
            user_id (int): The current user ID.
            filters (dict): Extra filter parameters (tags__overlap, vegan_status...).
            max_plant_milk_surcharge (Optional[float]): Keep restaurants whose
                plant milk surcharge is at most this value, and the fully vegan
                ones (no cow milk to compare with).
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
            or_(
                and_(self._model.latitude.between(min_lat, max_lat),
                     self._model.longitude.between(min_lng, max_lng)),
                and_(self._model.stops.isnot(None),
                     func.jsonb_path_exists(
                         self._model.stops,
                         '$[*] ? (@.latitude >= $min_lat && @.latitude <= $max_lat'
                         ' && @.longitude >= $min_lng && @.longitude <= $max_lng)',
                         func.jsonb_build_object(
                             'min_lat', min_lat, 'max_lat', max_lat,
                             'min_lng', min_lng, 'max_lng', max_lng))),
            ),
            self._model.date_deleted.is_(None),
            or_(self._model.validated.is_(True),
                self._model.created_by == user_id),
        )
        query = buildQueryFilters(self._model, query, filters or {})
        if max_plant_milk_surcharge is not None:
            query = query.filter(or_(
                self._model.plant_milk_surcharge <= max_plant_milk_surcharge,
                self._model.vegan_status == RestaurantVeganStatus.FULLY_VEGAN,
            ))
        return query.limit(limit).all()

    def search_by_name(
        self,
        db: Session,
        query_text: str,
        user_id: int,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        limit: int = 10,
        include_city: bool = False,
    ) -> List[Restaurant]:
        """
        Find the restaurants whose name (or city, with include_city)
        contains a text, to suggest them in the map search: validated ones,
        plus the pending ones created by the user. Any apostrophe matches
        any other (' or ’). Permanently closed ones
        are kept, so users learn they closed, but come last. Then name
        matches come before city ones, names starting with the text first,
        then the closest to the given point.

        Parameters:
            db (Session): The database session.
            query_text (str): The text to look for (case-insensitive).
            user_id (int): The current user ID.
            latitude (Optional[float]): The point to sort by distance from.
            longitude (Optional[float]): The point to sort by distance from.
            limit (int): Maximum number of restaurants to return (default 10).
            include_city (bool): Also match the city.

        Returns:
            List[Restaurant]: The matching restaurants.
        """
        pattern = search_pattern(query_text)
        name = without_apostrophe_variants(self._model.name)
        city = without_apostrophe_variants(self._model.city)
        starts_with = name.ilike(f"{pattern}%", escape='\\')
        name_matches = name.ilike(f"%{pattern}%", escape='\\')
        matches = or_(name_matches, city.ilike(
            f"%{pattern}%", escape='\\')) if include_city else name_matches
        query = db.query(self._model).options(
            noload(self._model.photos)
        ).filter(
            matches,
            self._model.date_deleted.is_(None),
            or_(self._model.validated.is_(True),
                self._model.created_by == user_id),
        )
        is_closed = self._model.operating_status == RestaurantOperatingStatus.PERMANENTLY_CLOSED
        order = [is_closed.asc()]
        if include_city:
            order.append(name_matches.desc())
        order.append(starts_with.desc())
        if latitude is not None and longitude is not None:
            # Squared degrees are enough to rank by proximity
            order.append(
                func.pow(self._model.latitude - latitude, 2)
                + func.pow(self._model.longitude - longitude, 2))
        order.append(self._model.name)
        return query.order_by(*order).limit(limit).all()

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
    def get_featured_by_restaurant(self, db: Session, restaurant_ids: List[int]) -> Dict[int, RestaurantPhoto]:
        """
        Get the featured photo of several restaurants at once (map pins),
        without loading all their photos.

        Parameters:
            db (Session): The database session.
            restaurant_ids (List[int]): The restaurant IDs.

        Returns:
            Dict[int, RestaurantPhoto]: The featured photo by restaurant ID,
                for those having one.
        """
        if not restaurant_ids:
            return {}
        candidates = db.query(self._model).filter(
            self._model.restaurant_id.in_(restaurant_ids),
            self._model.review_id.is_(None),
            self._model.status == RestaurantPhotoStatus.APPROVED,
            or_(self._model.is_featured.is_(True),
                self._model.kind == RestaurantPhotoKind.PLACE),
        ).all()
        by_restaurant = defaultdict(list)
        for photo in candidates:
            by_restaurant[photo.restaurant_id].append(photo)
        return {
            restaurant_id: pick_featured_photo(photos)
            for restaurant_id, photos in by_restaurant.items()
        }

    def set_featured(self, db: Session, photo: RestaurantPhoto) -> RestaurantPhoto:
        """
        Make a photo the featured one of its restaurant, replacing the
        previous one.

        Parameters:
            db (Session): The database session.
            photo (RestaurantPhoto): The photo to feature.

        Returns:
            RestaurantPhoto: The featured photo.
        """
        db.query(self._model).filter(
            self._model.restaurant_id == photo.restaurant_id,
            self._model.is_featured.is_(True),
        ).update({"is_featured": False})
        # Unique index: the previous one must be cleared first
        db.flush()
        photo.is_featured = True
        db.commit()
        db.refresh(photo)
        return photo

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


class RestaurantSaveCRUDRepository(CRUDRepository):
    def get_saved_ids(self, db: Session, user_id: int, restaurant_ids: List[int]) -> set:
        """
        Get which of some restaurants the user saved.

        Parameters:
            db (Session): The database session.
            user_id (int): The user ID.
            restaurant_ids (List[int]): The restaurant IDs.

        Returns:
            set: The IDs of the saved ones.
        """
        if not restaurant_ids:
            return set()
        rows = db.query(self._model.restaurant_id).filter(
            self._model.user_id == user_id,
            self._model.restaurant_id.in_(restaurant_ids),
        ).all()
        return {restaurant_id for restaurant_id, in rows}

    def save(self, db: Session, user_id: int, restaurant_id: int) -> None:
        """
        Save a restaurant for the user; nothing to do when already saved.

        Parameters:
            db (Session): The database session.
            user_id (int): The user ID.
            restaurant_id (int): The restaurant ID.
        """
        exists = db.query(self._model.id).filter(
            self._model.user_id == user_id,
            self._model.restaurant_id == restaurant_id,
        ).first()
        if exists:
            return
        db.add(self._model(user_id=user_id, restaurant_id=restaurant_id))
        db.commit()

    def unsave(self, db: Session, user_id: int, restaurant_id: int) -> None:
        """
        Remove a restaurant from the user's saved ones, if there.

        Parameters:
            db (Session): The database session.
            user_id (int): The user ID.
            restaurant_id (int): The restaurant ID.
        """
        db.query(self._model).filter(
            self._model.user_id == user_id,
            self._model.restaurant_id == restaurant_id,
        ).delete()
        db.commit()

    def get_saved_restaurants(
        self,
        db: Session,
        user_id: int,
        skip: int = 0,
        limit: int = 20
    ) -> Tuple[List[Restaurant], int]:
        """
        Get the restaurants saved by the user, last saved first: the ones
        still visible to them (validated, or created by them). Permanently
        closed ones are kept, so the user learns they closed.

        Parameters:
            db (Session): The database session.
            user_id (int): The user ID.
            skip (int): Number of records to skip.
            limit (int): Maximum number of records to retrieve.

        Returns:
            Tuple[List[Restaurant], int]: The restaurants and total count.
        """
        query = db.query(Restaurant).join(
            self._model, self._model.restaurant_id == Restaurant.id
        ).filter(
            self._model.user_id == user_id,
            Restaurant.date_deleted.is_(None),
            or_(Restaurant.validated.is_(True),
                Restaurant.created_by == user_id),
        )
        total = query.count()
        restaurants = query.order_by(
            self._model.created_at.desc()).offset(skip).limit(limit).all()
        return restaurants, total


restaurant_crud = RestaurantCRUDRepository(model=Restaurant)
restaurant_photo_crud = RestaurantPhotoCRUDRepository(model=RestaurantPhoto)
restaurant_save_crud = RestaurantSaveCRUDRepository(model=RestaurantSave)
