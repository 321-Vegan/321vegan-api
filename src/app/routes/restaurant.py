import uuid
from pathlib import Path
from typing import List, Optional, Tuple

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.routes.dependencies import get_current_active_user, get_pagination_params, get_sort_by_params, RoleChecker
from app.crud.restaurant import restaurant_crud, restaurant_photo_crud, restaurant_save_crud
from app.crud.restaurant_lock import restaurant_lock_crud
from app.database.db import get_db
from app.log import get_logger
from app.models import User
from app.models.user import UserRole
from app.models.restaurant import Restaurant, RestaurantServiceOption, RestaurantTag, RestaurantVeganStatus
from app.models.restaurant_photo import RestaurantPhoto, RestaurantPhotoKind, RestaurantPhotoStatus
from app.models.restaurant_lock import RestaurantLock
from app.services.s3_file_manager import s3_file_manager
from app.schemas.restaurant import (
    compute_restaurant_change,
    RestaurantCreate,
    RestaurantDelete,
    RestaurantUpdate,
    RestaurantOut,
    RestaurantMapOut,
    RestaurantOutPaginated,
    RestaurantFilters,
    RestaurantEditOut,
    RestaurantPhotoOut,
    RestaurantPhotoOutPaginated,
    RestaurantPhotoFilters,
    RestaurantPhotoStatusUpdate,
    RestaurantPhotoKindUpdate,
    RestaurantLockOut,
)

log = get_logger(__name__)

router = APIRouter(dependencies=[Depends(get_current_active_user)])

MAX_PHOTOS_PER_KIND = 10


def _is_moderator(user: User) -> bool:
    return user.has_role(UserRole.MODERATOR)


def _lock_out(lock: RestaurantLock) -> RestaurantLockOut:
    return RestaurantLockOut(locked_by=lock.user.nickname, locked_at=lock.locked_at)


def _check_lock(db: Session, restaurant: Restaurant, user: User) -> None:
    """
    Raise a 423 error, with the lock as detail, when another moderator holds
    a live validation lock on the restaurant. The lock only concerns
    moderators: a creator editing their pending restaurant is never blocked.
    """
    if not _is_moderator(user):
        return
    lock = restaurant_lock_crud.get_live_lock(db, restaurant)
    if lock and lock.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=jsonable_encoder(_lock_out(lock)),
        )


def _parse_values(values: Optional[List[str]], enum_class, what: str) -> List[str]:
    """Accept repeated params or comma-separated values, reject unknown ones."""
    parsed = []
    for value in values or []:
        parsed.extend(v.strip() for v in value.split(',') if v.strip())
    known = {member.value for member in enum_class}
    unknown = [value for value in parsed if value not in known]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown {what}: {', '.join(unknown)}",
        )
    return parsed


def _parse_tags(values: Optional[List[str]]) -> List[str]:
    return _parse_values(values, RestaurantTag, "tags")


def _get_visible_restaurant(db: Session, id: int, user: User) -> Restaurant:
    """
    A pending restaurant is only visible to its creator and the moderators.

    Raises:
        HTTPException: If the restaurant does not exist or is not visible.
    """
    restaurant = restaurant_crud.get_by_id(db, id)
    if restaurant is None or not (
        restaurant.validated
        or restaurant.created_by == user.id
        or _is_moderator(user)
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found"
        )
    return restaurant


def _restaurant_out(
    restaurant: Restaurant,
    user: User,
    db: Session,
    saved_ids: Optional[set] = None,
) -> RestaurantOut:
    """
    Restaurant as seen by the user: approved place and menu photos plus the
    user's own pending ones (all of them for moderators), no address for a
    caterer without storefront, and whether the user saved it.

    Parameters:
        saved_ids (Optional[set]): The restaurants saved by the user, when
            already known (lists); looked up otherwise.
    """
    if saved_ids is None:
        saved_ids = restaurant_save_crud.get_saved_ids(
            db, user.id, [restaurant.id])
    out = RestaurantOut.model_validate(restaurant)
    is_moderator = _is_moderator(user)
    is_creator = restaurant.created_by == user.id
    photos = [
        photo for photo in out.photos
        if photo.review_id is None and (
            is_moderator
            or photo.status == RestaurantPhotoStatus.APPROVED
            or photo.user_id == user.id
        )
    ]
    update = {"photos": photos, "is_saved": restaurant.id in saved_ids}
    if not restaurant.has_storefront and not (is_moderator or is_creator):
        update["address"] = None
    return out.model_copy(update=update)


def _map_out(
    restaurant: Restaurant,
    rating_avg: Optional[float] = None,
    review_count: Optional[int] = None,
    featured_photo: Optional[RestaurantPhoto] = None,
) -> RestaurantMapOut:
    return RestaurantMapOut.model_validate(restaurant).model_copy(update={
        "rating_avg": round(float(rating_avg), 1) if rating_avg is not None else None,
        "review_count": review_count or 0,
        "featured_photo": RestaurantPhotoOut.model_validate(featured_photo) if featured_photo else None,
    })


@router.get(
    "/in-area", response_model=List[RestaurantMapOut], status_code=status.HTTP_200_OK
)
def fetch_restaurants_in_area(
    min_lat: float = Query(..., ge=-90, le=90),
    max_lat: float = Query(..., ge=-90, le=90),
    min_lng: float = Query(..., ge=-180, le=180),
    max_lng: float = Query(..., ge=-180, le=180),
    tags: Optional[List[str]] = Query(default=None),
    service_options: Optional[List[str]] = Query(default=None),
    vegan_status: Optional[RestaurantVeganStatus] = Query(default=None),
    plant_milk_surcharge__le: Optional[float] = Query(default=None),
    has_gluten_free_options: Optional[bool] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> List[RestaurantMapOut]:
    """
    Fetch the restaurants to show on the map within a bounding box: validated
    ones, plus the pending ones created by the user. Permanently closed
    restaurants are kept so the app can show them as closed.

    Parameters:
        min_lat/max_lat/min_lng/max_lng (float): The bounding box.
        tags (List[str]): Keep restaurants with at least one of these tags.
            Supports repeated params or comma-separated values.
        service_options (List[str]): Keep restaurants offering at least one of
            these (dine_in, takeaway, delivery).
        vegan_status (RestaurantVeganStatus): Keep only this vegan status.
        plant_milk_surcharge__le (float): Keep restaurants whose plant milk
            surcharge is at most this value (0 = no surcharge). Fully vegan
            places have no cow milk to compare with, so they are kept.
        has_gluten_free_options (bool): Keep only restaurants with (or
            without) gluten free vegan options.
        db (Session): The database session.
        current_user (User): The current authenticated user.

    Returns:
        List[RestaurantMapOut]: The restaurants with their rating (max 300).
    """
    filters = {}
    parsed_tags = _parse_tags(tags)
    if parsed_tags:
        filters['tags__overlap'] = parsed_tags
    parsed_options = _parse_values(
        service_options, RestaurantServiceOption, "service options")
    if parsed_options:
        filters['service_options__overlap'] = parsed_options
    if vegan_status is not None:
        filters['vegan_status'] = vegan_status
    if has_gluten_free_options is not None:
        filters['has_gluten_free_options'] = has_gluten_free_options
    rows = restaurant_crud.get_in_bounding_box(
        db, min_lat, max_lat, min_lng, max_lng, current_user.id, filters,
        max_plant_milk_surcharge=plant_milk_surcharge__le)
    featured = restaurant_photo_crud.get_featured_by_restaurant(
        db, [restaurant.id for restaurant, _, _ in rows])
    return [_map_out(restaurant, rating_avg, review_count, featured.get(restaurant.id))
            for restaurant, rating_avg, review_count in rows]


@router.get(
    "/search",
    response_model=Optional[RestaurantOutPaginated],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(RoleChecker(["moderator"]))],
)
def fetch_paginated_restaurants(
    filter_params: RestaurantFilters = Depends(),
    tags: Optional[List[str]] = Query(default=None),
    db: Session = Depends(get_db),
    pagination_params: Tuple[int, int] = Depends(get_pagination_params),
    orderby_params: Tuple[str, bool] = Depends(get_sort_by_params),
) -> Optional[RestaurantOutPaginated]:
    """
    Fetch many restaurants with pagination and filters (moderators only).

    Parameters:
        filter_params (RestaurantFilters): Filter parameters.
        tags (List[str]): Keep restaurants with at least one of these tags.
        db (Session): The database session.
        pagination_params (Tuple[int, int]): The pagination parameters (skip, limit).
        orderby_params (Tuple[str, bool]): The order by parameters (sortby, descending).

    Returns:
        RestaurantOutPaginated: The list of restaurants with pagination data.
    """
    skip, size = pagination_params
    sortby, descending = orderby_params
    filters = filter_params.model_dump(exclude_none=True)
    parsed_tags = _parse_tags(tags)
    if parsed_tags:
        filters['tags__overlap'] = parsed_tags
    restaurants, total = restaurant_crud.get_many(
        db,
        skip=skip,
        limit=size,
        order_by=sortby,
        descending=descending,
        filters=filters
    )
    pages = (total + size - 1) // size
    return {
        "items": restaurants,
        "total": total,
        "page": skip // size + 1,
        "size": size,
        "pages": pages
    }


@router.get(
    "/mine",
    response_model=RestaurantOutPaginated,
    status_code=status.HTTP_200_OK,
)
def fetch_my_restaurants(
    db: Session = Depends(get_db),
    pagination_params: Tuple[int, int] = Depends(get_pagination_params),
    current_user: User = Depends(get_current_active_user),
) -> RestaurantOutPaginated:
    """
    Fetch the restaurants created by the current user (pending, validated,
    or refused with the reason), newest first.

    Parameters:
        db (Session): The database session.
        pagination_params (Tuple[int, int]): The pagination parameters (skip, limit).
        current_user (User): The current authenticated user.

    Returns:
        RestaurantOutPaginated: The user's restaurants with pagination data.
    """
    skip, size = pagination_params
    restaurants, total = restaurant_crud.get_created_by(
        db, current_user.id, skip=skip, limit=size)
    saved_ids = restaurant_save_crud.get_saved_ids(
        db, current_user.id, [restaurant.id for restaurant in restaurants])
    pages = (total + size - 1) // size
    return {
        "items": [_restaurant_out(restaurant, current_user, db, saved_ids)
                  for restaurant in restaurants],
        "total": total,
        "page": skip // size + 1,
        "size": size,
        "pages": pages,
    }


@router.get(
    "/saved",
    response_model=RestaurantOutPaginated,
    status_code=status.HTTP_200_OK,
)
def fetch_saved_restaurants(
    db: Session = Depends(get_db),
    pagination_params: Tuple[int, int] = Depends(get_pagination_params),
    current_user: User = Depends(get_current_active_user),
) -> RestaurantOutPaginated:
    """
    Fetch the restaurants saved by the current user, last saved first.
    Permanently closed ones are kept so the user learns they closed.

    Parameters:
        db (Session): The database session.
        pagination_params (Tuple[int, int]): The pagination parameters (skip, limit).
        current_user (User): The current authenticated user.

    Returns:
        RestaurantOutPaginated: The saved restaurants with pagination data.
    """
    skip, size = pagination_params
    restaurants, total = restaurant_save_crud.get_saved_restaurants(
        db, current_user.id, skip=skip, limit=size)
    saved_ids = {restaurant.id for restaurant in restaurants}
    pages = (total + size - 1) // size
    return {
        "items": [_restaurant_out(restaurant, current_user, db, saved_ids)
                  for restaurant in restaurants],
        "total": total,
        "page": skip // size + 1,
        "size": size,
        "pages": pages,
    }


@router.put("/{id}/saved", status_code=status.HTTP_204_NO_CONTENT)
def save_restaurant(
    id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """
    Save a restaurant for the current user (no-op when already saved).

    Parameters:
        id (int): The ID of the restaurant.
        db (Session): The database session.
        current_user (User): The current authenticated user.
    """
    restaurant = _get_visible_restaurant(db, id, current_user)
    restaurant_save_crud.save(db, current_user.id, restaurant.id)


@router.delete("/{id}/saved", status_code=status.HTTP_204_NO_CONTENT)
def unsave_restaurant(
    id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """
    Remove a restaurant from the current user's saved ones (no-op when not
    saved). Works even if the restaurant is no longer visible.

    Parameters:
        id (int): The ID of the restaurant.
        db (Session): The database session.
        current_user (User): The current authenticated user.
    """
    restaurant_save_crud.unsave(db, current_user.id, id)


@router.get(
    "/nearby", response_model=List[RestaurantMapOut], status_code=status.HTTP_200_OK
)
def fetch_nearby_restaurants(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    radius: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
) -> List[RestaurantMapOut]:
    """
    Fetch the restaurants (validated or pending) close to a point, closest
    first, to spot a duplicate before creating a restaurant.

    Parameters:
        latitude (float): The latitude to search around.
        longitude (float): The longitude to search around.
        radius (int): The search radius in meters (default 50).
        db (Session): The database session.

    Returns:
        List[RestaurantMapOut]: The restaurants within the radius.
    """
    restaurants = restaurant_crud.find_all_nearby(
        db, latitude, longitude, radius)
    return [_map_out(restaurant) for restaurant in restaurants]


@router.get(
    "/search-name", response_model=List[RestaurantMapOut], status_code=status.HTTP_200_OK
)
def search_restaurants_by_name(
    q: str = Query(..., min_length=2, max_length=100),
    latitude: Optional[float] = Query(default=None, ge=-90, le=90),
    longitude: Optional[float] = Query(default=None, ge=-180, le=180),
    include_city: bool = Query(default=False),
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> List[RestaurantMapOut]:
    """
    Search restaurants by name (or city) for the map search suggestions and
    the places to add to a selection: validated ones, plus the pending ones
    created by the user. Permanently closed restaurants are kept (last) so
    the app can show them as closed.

    Parameters:
        q (str): The text the name must contain (case-insensitive).
        latitude (float): The point to sort by distance from (map center).
        longitude (float): The point to sort by distance from (map center).
        include_city (bool): Also match the city (name matches first).
        limit (int): Maximum number of restaurants (default 10, max 50).
        db (Session): The database session.
        current_user (User): The current authenticated user.

    Returns:
        List[RestaurantMapOut]: The matching restaurants: open ones first,
            names starting with the text first, then the closest.
    """
    restaurants = restaurant_crud.search_by_name(
        db, q, current_user.id, latitude, longitude,
        limit=limit, include_city=include_city)
    return [_map_out(restaurant) for restaurant in restaurants]


@router.get(
    "/photos/search",
    response_model=RestaurantPhotoOutPaginated,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(RoleChecker(["moderator"]))],
)
def fetch_paginated_photos(
    filter_params: RestaurantPhotoFilters = Depends(),
    db: Session = Depends(get_db),
    pagination_params: Tuple[int, int] = Depends(get_pagination_params),
    orderby_params: Tuple[str, bool] = Depends(get_sort_by_params),
) -> RestaurantPhotoOutPaginated:
    """
    Search the place and menu photos of validated restaurants, e.g. the
    pending ones to moderate (moderators only). Review photos follow their
    review, and the photos of a pending restaurant are approved with it, so
    both are left out.

    Parameters:
        filter_params (RestaurantPhotoFilters): Filter parameters.
        db (Session): The database session.
        pagination_params (Tuple[int, int]): The pagination parameters (skip, limit).
        orderby_params (Tuple[str, bool]): The order by parameters (sortby, descending).

    Returns:
        RestaurantPhotoOutPaginated: The photos with their restaurant.
    """
    skip, size = pagination_params
    sortby, descending = orderby_params
    filters = filter_params.model_dump(exclude_none=True)
    filters['review_id__isnull'] = True
    filters['restaurant___validated'] = True
    filters['restaurant___date_deleted__isnull'] = True
    photos, total = restaurant_photo_crud.get_many(
        db,
        skip=skip,
        limit=size,
        order_by=sortby,
        descending=descending,
        **filters
    )
    pages = (total + size - 1) // size
    return {
        "items": photos,
        "total": total,
        "page": skip // size + 1,
        "size": size,
        "pages": pages,
    }


@router.patch(
    "/photos/{photo_id}/status",
    response_model=RestaurantPhotoOut,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(RoleChecker(["moderator"]))],
)
def update_photo_status(
    photo_id: int,
    status_in: RestaurantPhotoStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> RestaurantPhotoOut:
    """
    Approve or reject a place or menu photo (contributor or admin only).
    A review photo follows the status of its review.

    Parameters:
        photo_id (int): The photo ID.
        status_in (RestaurantPhotoStatusUpdate): The new status.
        db (Session): The database session.
        current_user (User): The current moderator user.

    Returns:
        RestaurantPhotoOut: The updated photo.
    """
    photo = restaurant_photo_crud.get_by_id(db, photo_id)
    if photo is None or photo.review_id is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Photo not found"
        )
    updated_photo = restaurant_photo_crud.update(db, photo, status_in)
    log.info(
        f"Restaurant photo {photo_id} status updated to {status_in.status} by moderator {current_user.id}")
    return updated_photo


@router.patch(
    "/photos/{photo_id}/kind",
    response_model=RestaurantPhotoOut,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(RoleChecker(["moderator"]))],
)
def update_photo_kind(
    photo_id: int,
    kind_in: RestaurantPhotoKindUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> RestaurantPhotoOut:
    """
    Move a place photo to the menu photos or the other way round, when it was
    sent in the wrong one (moderators only). Its file keeps its path.

    Parameters:
        photo_id (int): The photo ID.
        kind_in (RestaurantPhotoKindUpdate): The new kind.
        db (Session): The database session.
        current_user (User): The current moderator user.

    Returns:
        RestaurantPhotoOut: The updated photo.
    """
    photo = restaurant_photo_crud.get_by_id(db, photo_id)
    if photo is None or photo.review_id is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Photo not found"
        )
    if photo.kind == kind_in.kind:
        return photo
    if restaurant_photo_crud.count_for_kind(db, photo.restaurant_id, kind_in.kind) >= MAX_PHOTOS_PER_KIND:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"A restaurant cannot have more than {MAX_PHOTOS_PER_KIND} photos of this kind",
        )
    updated_photo = restaurant_photo_crud.update(db, photo, kind_in)
    log.info(
        f"Restaurant photo {photo_id} kind updated to {kind_in.kind} by moderator {current_user.id}")
    return updated_photo


@router.get(
    "/{id}/history",
    response_model=List[RestaurantEditOut],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(RoleChecker(["moderator"]))],
)
def fetch_restaurant_history(
    id: int, db: Session = Depends(get_db)
) -> List[RestaurantEditOut]:
    """
    Fetch the changes applied to a restaurant, newest first (moderators only).

    Parameters:
        id (int): The ID of the restaurant.
        db (Session): The database session.

    Returns:
        List[RestaurantEditOut]: The restaurant history.
    """
    if restaurant_crud.get_by_id(db, id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found"
        )
    return restaurant_crud.get_history(db, id)


@router.get(
    "/{id}",
    response_model=RestaurantOut,
    status_code=status.HTTP_200_OK,
)
def fetch_restaurant_by_id(
    id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> RestaurantOut:
    """
    Fetches a restaurant by its ID, with its place and menu photos.

    Parameters:
        id (int): The ID of the restaurant.
        db (Session): The database session.
        current_user (User): The current authenticated user.

    Returns:
        RestaurantOut: The restaurant.
    """
    restaurant = _get_visible_restaurant(db, id, current_user)
    return _restaurant_out(restaurant, current_user, db)


@router.post(
    "/", response_model=RestaurantOut, status_code=status.HTTP_201_CREATED
)
def create_restaurant(
    restaurant_in: RestaurantCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> RestaurantOut:
    """
    Create a new restaurant. Any authenticated user can submit one; it stays
    pending until a moderator validates it. A restaurant created by an
    admin is validated right away (contributors' ones are checked too).

    Parameters:
        restaurant_in (RestaurantCreate): The restaurant data.
        db (Session): The database session.
        current_user (User): The current authenticated user.

    Returns:
        RestaurantOut: The created restaurant.
    """
    restaurant = restaurant_crud.create_for_user(
        db,
        restaurant_in.model_dump(),
        user_id=current_user.id,
        validated=_is_moderator(current_user),
    )
    log.info(
        f"Restaurant created: {restaurant.name} (ID: {restaurant.id}) by user {current_user.id}")
    return _restaurant_out(restaurant, current_user, db)


@router.put(
    "/{id}",
    response_model=RestaurantOut,
    status_code=status.HTTP_200_OK,
)
def update_restaurant(
    id: int,
    restaurant_in: RestaurantUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> RestaurantOut:
    """
    Update a restaurant directly: by its creator while it is pending, by a
    moderator at any time. Only moderators can validate it. Every change is
    recorded in the restaurant history.

    Parameters:
        id (int): The ID of the restaurant.
        restaurant_in (RestaurantUpdate): The changed fields.
        db (Session): The database session.
        current_user (User): The current authenticated user.

    Returns:
        RestaurantOut: The updated restaurant.
    """
    restaurant = _get_visible_restaurant(db, id, current_user)
    is_moderator = _is_moderator(current_user)
    if not is_moderator and (restaurant.validated or restaurant.created_by != current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only moderators can edit a validated restaurant: suggest a change instead",
        )
    _check_lock(db, restaurant, current_user)

    changes = restaurant_in.model_dump(exclude_unset=True)
    validated = changes.pop('validated', None)
    if validated is not None and not is_moderator:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only moderators can validate a restaurant",
        )

    # Check the business rules on the restaurant as it will be
    try:
        values, before, after = compute_restaurant_change(restaurant, changes)
    except ValidationError as e:
        raise RequestValidationError(
            e.errors(include_url=False, include_context=False))

    if validated is not None and validated != restaurant.validated:
        values['validated'] = validated
        before['validated'] = restaurant.validated
        after['validated'] = validated

    if not values:
        return _restaurant_out(restaurant, current_user, db)

    updated_restaurant = restaurant_crud.update_with_history(
        db, restaurant, values, before, after, user_id=current_user.id)
    # The work is done: release the user's lock
    restaurant_lock_crud.unlock(db, updated_restaurant, current_user)
    log.info(
        f"Restaurant updated: {updated_restaurant.name} (ID: {id}) by user {current_user.id}, fields {list(values)}")
    return _restaurant_out(updated_restaurant, current_user, db)


@router.delete(
    "/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RoleChecker(["moderator"]))],
)
def delete_restaurant(
    id: int,
    delete_in: Optional[RestaurantDelete] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """
    Soft-delete a restaurant: sets date_deleted instead of removing the row,
    so its reviews and photos are preserved. A pending one is refused: it
    stays in its creator's list, with the reason if given.

    Parameters:
        id (int): The ID of the restaurant.
        delete_in (Optional[RestaurantDelete]): The refusal reason, if any.
        db (Session): The database session.
        current_user (User): The current authenticated user.
    """
    restaurant = restaurant_crud.get_by_id(db, id)
    if restaurant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found"
        )
    _check_lock(db, restaurant, current_user)

    reason = None
    if not restaurant.validated and delete_in is not None:
        reason = (delete_in.rejection_reason or "").strip() or None
    restaurant_crud.soft_delete(db, restaurant, rejection_reason=reason)
    restaurant_lock_crud.unlock(db, restaurant, current_user)
    log.info(f"Restaurant soft-deleted: ID {id}")


@router.post(
    "/{id}/lock",
    response_model=RestaurantLockOut,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(RoleChecker(["moderator"]))],
)
def lock_restaurant(
    id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> RestaurantLockOut:
    """
    Take or renew the validation lock of a restaurant, so that two
    moderators don't work on it at the same time. The lock expires after
    RESTAURANT_LOCK_DURATION without being renewed.

    Parameters:
        id (int): The ID of the restaurant to lock.
        db (Session): The database session.
        current_user (User): The current moderator user.

    Returns:
        RestaurantLockOut: The lock taken by the user.

    Raises:
        HTTPException: If the restaurant is not found.
        HTTPException: If another user holds a live lock (423),
            with this lock as detail.
    """
    restaurant = restaurant_crud.get_by_id(db, id)
    if restaurant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found"
        )
    lock = restaurant_lock_crud.lock(db, restaurant, current_user)
    if lock.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=jsonable_encoder(_lock_out(lock)),
        )
    return _lock_out(lock)


@router.delete(
    "/{id}/lock",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RoleChecker(["moderator"]))],
)
def unlock_restaurant(
    id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """
    Release the validation lock of a restaurant. Does nothing if the lock is
    held by another user.

    Parameters:
        id (int): The ID of the restaurant to unlock.
        db (Session): The database session.
        current_user (User): The current moderator user.

    Raises:
        HTTPException: If the restaurant is not found.
    """
    restaurant = restaurant_crud.get_by_id(db, id)
    if restaurant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found"
        )
    restaurant_lock_crud.unlock(db, restaurant, current_user)


@router.post(
    "/{id}/photos",
    response_model=RestaurantPhotoOut,
    status_code=status.HTTP_201_CREATED,
)
def upload_restaurant_photo(
    id: int,
    kind: RestaurantPhotoKind = Form(...),
    file: UploadFile = File(...,
                            description="Image (JPG, PNG, WebP max 5MB)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> RestaurantPhotoOut:
    """
    Add a place or menu photo to a restaurant. It is stored in the bucket
    under restaurants/{id}/. A moderator's photo is approved right away;
    others wait for moderation (or for the restaurant validation, for the
    photos sent with a new restaurant).

    Parameters:
        id (int): The ID of the restaurant.
        kind (RestaurantPhotoKind): PLACE or MENU.
        file (UploadFile): Image file (JPG, PNG, WebP, max 5MB).
        db (Session): The database session.
        current_user (User): The current authenticated user.

    Returns:
        RestaurantPhotoOut: The created photo.
    """
    restaurant = _get_visible_restaurant(db, id, current_user)
    if restaurant_photo_crud.count_for_kind(db, id, kind) >= MAX_PHOTOS_PER_KIND:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"A restaurant cannot have more than {MAX_PHOTOS_PER_KIND} photos of this kind",
        )

    file_extension = Path(file.filename or "").suffix.lower()
    object_name = f"restaurants/{restaurant.id}/{kind.value.lower()}_{uuid.uuid4().hex}{file_extension}"
    s3_file_manager.upload_image(object_name, file)

    photo = RestaurantPhoto(
        restaurant_id=restaurant.id,
        kind=kind,
        path=object_name,
        status=RestaurantPhotoStatus.APPROVED if _is_moderator(
            current_user) else RestaurantPhotoStatus.PENDING,
        user_id=current_user.id,
    )
    try:
        db.add(photo)
        db.commit()
        db.refresh(photo)
    except IntegrityError as e:
        db.rollback()
        s3_file_manager.delete_file(object_name)
        log.error(f"Error saving restaurant photo: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Error saving photo",
        )
    log.info(
        f"Restaurant photo added: {object_name} (ID: {photo.id}) by user {current_user.id}")
    return photo


@router.patch(
    "/{id}/photos/{photo_id}/featured",
    response_model=RestaurantPhotoOut,
    status_code=status.HTTP_200_OK,
)
def feature_restaurant_photo(
    id: int,
    photo_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> RestaurantPhotoOut:
    """
    Make a place or menu photo the one shown first on the restaurant page,
    replacing the previous one. A moderator, or the creator while the
    restaurant is pending. It only shows once approved.

    Parameters:
        id (int): The ID of the restaurant.
        photo_id (int): The ID of the photo.
        db (Session): The database session.
        current_user (User): The current authenticated user.

    Returns:
        RestaurantPhotoOut: The featured photo.
    """
    restaurant = _get_visible_restaurant(db, id, current_user)
    if not _is_moderator(current_user) and (
        restaurant.validated or restaurant.created_by != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only moderators can choose the featured photo",
        )
    photo = restaurant_photo_crud.get_by_id(db, photo_id)
    if photo is None or photo.restaurant_id != id or photo.review_id is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Photo not found"
        )
    featured = restaurant_photo_crud.set_featured(db, photo)
    log.info(
        f"Restaurant photo {photo_id} featured for restaurant {id} by user {current_user.id}")
    return featured


@router.delete(
    "/{id}/photos/{photo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_restaurant_photo(
    id: int,
    photo_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """
    Delete a place or menu photo. Its author or a moderator only.

    Parameters:
        id (int): The ID of the restaurant.
        photo_id (int): The ID of the photo.
        db (Session): The database session.
        current_user (User): The current authenticated user.
    """
    photo = restaurant_photo_crud.get_by_id(db, photo_id)
    if photo is None or photo.restaurant_id != id or photo.review_id is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Photo not found"
        )
    if photo.user_id != current_user.id and not _is_moderator(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete your own photos",
        )

    path = photo.path
    restaurant_photo_crud.delete(db, photo)
    s3_file_manager.delete_file(path)
    log.info(f"Restaurant photo deleted: {photo_id} by user {current_user.id}")
