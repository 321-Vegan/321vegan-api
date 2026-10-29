from datetime import datetime, timezone
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.routes.dependencies import get_current_active_user, get_pagination_params, get_sort_by_params, RoleChecker
from app.crud.restaurant import restaurant_crud
from app.crud.restaurant_edit_suggestion import restaurant_edit_suggestion_crud
from app.database.db import get_db
from app.log import get_logger
from app.models import User
from app.models.user import UserRole
from app.models.restaurant import Restaurant
from app.models.restaurant_photo import RestaurantPhoto, RestaurantPhotoStatus
from app.models.restaurant_edit_suggestion import (
    RestaurantEditSuggestion,
    RestaurantEditSuggestionKind,
    RestaurantEditSuggestionStatus,
)
from app.services.s3_file_manager import s3_file_manager
from app.schemas.restaurant import RestaurantBase, RestaurantPhotoOut, compute_restaurant_change, restaurant_state
from app.schemas.restaurant_edit_suggestion import (
    FEATURED_PHOTO_ID,
    REMOVE_PHOTO_IDS,
    RestaurantSuggestionCreate,
    RestaurantSuggestionApply,
    RestaurantSuggestionReject,
    RestaurantSuggestionOut,
    RestaurantSuggestionOutPaginated,
    RestaurantSuggestionOutCount,
    RestaurantSuggestionFilters,
)

log = get_logger(__name__)

router = APIRouter(dependencies=[Depends(get_current_active_user)])


def _is_moderator(user: User) -> bool:
    return user.has_role(UserRole.MODERATOR)


def _validation_error(e: ValidationError) -> RequestValidationError:
    return RequestValidationError(e.errors(include_url=False, include_context=False))


def _get_listed_restaurant(db: Session, id: int) -> Restaurant:
    """
    Raises:
        HTTPException: If the restaurant is not a validated, listed one.
    """
    restaurant = restaurant_crud.get_by_id(db, id)
    if restaurant is None or not restaurant.validated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found"
        )
    return restaurant


def _removable_photos(db: Session, restaurant_id: int, photo_ids) -> list:
    """The approved place and menu photos of the restaurant among photo_ids."""
    if not photo_ids:
        return []
    return db.query(RestaurantPhoto).filter(
        RestaurantPhoto.id.in_(photo_ids),
        RestaurantPhoto.restaurant_id == restaurant_id,
        RestaurantPhoto.review_id.is_(None),
        RestaurantPhoto.status == RestaurantPhotoStatus.APPROVED,
    ).all()


def _featured_photo_id(restaurant: Optional[Restaurant]) -> Optional[int]:
    """The ID of the photo the restaurant shows first now, if any."""
    featured = restaurant.featured_photo if restaurant is not None else None
    return featured.id if featured else None


def _current_values(db: Session, suggestion: RestaurantEditSuggestion) -> Optional[dict]:
    """Current values of the fields an edit changes, to spot conflicts."""
    if not suggestion.changes or suggestion.restaurant is None:
        return None
    state = restaurant_state(suggestion.restaurant)
    try:
        current = RestaurantBase.model_validate(state).model_dump(mode="json")
    except ValidationError:
        current = jsonable_encoder(state)
    values = {field: current.get(field)
              for field in suggestion.changes
              if field not in (REMOVE_PHOTO_IDS, FEATURED_PHOTO_ID)}
    if FEATURED_PHOTO_ID in suggestion.changes:
        values[FEATURED_PHOTO_ID] = _featured_photo_id(suggestion.restaurant)
    if REMOVE_PHOTO_IDS in suggestion.changes:
        values[REMOVE_PHOTO_IDS] = [
            photo.id for photo in _removable_photos(
                db, suggestion.restaurant_id, suggestion.changes[REMOVE_PHOTO_IDS])
        ]
    return values


def _out(db: Session, suggestion: RestaurantEditSuggestion) -> RestaurantSuggestionOut:
    changes = suggestion.changes or {}
    photos = _removable_photos(
        db, suggestion.restaurant_id, changes.get(REMOVE_PHOTO_IDS))
    update = {
        "current_values": _current_values(db, suggestion),
        "photos_to_remove": [RestaurantPhotoOut.model_validate(photo) for photo in photos],
    }
    if FEATURED_PHOTO_ID in changes:
        proposed = _removable_photos(
            db, suggestion.restaurant_id, [changes[FEATURED_PHOTO_ID]])
        current = suggestion.restaurant.featured_photo if suggestion.restaurant else None
        update["proposed_featured_photo"] = \
            RestaurantPhotoOut.model_validate(proposed[0]) if proposed else None
        update["current_featured_photo"] = \
            RestaurantPhotoOut.model_validate(current) if current else None
    return RestaurantSuggestionOut.model_validate(suggestion).model_copy(update=update)


def _get_suggestion(db: Session, id: int, user: User) -> RestaurantEditSuggestion:
    """
    Raises:
        HTTPException: If the suggestion doesn't exist or isn't the user's
            (moderators see them all).
    """
    suggestion = restaurant_edit_suggestion_crud.get_by_id(db, id)
    if suggestion is None or not (suggestion.user_id == user.id or _is_moderator(user)):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Suggestion not found"
        )
    return suggestion


def _get_pending_suggestion(db: Session, id: int, user: User) -> RestaurantEditSuggestion:
    suggestion = _get_suggestion(db, id, user)
    if suggestion.status != RestaurantEditSuggestionStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This suggestion was already reviewed"
        )
    return suggestion


@router.get(
    "/count",
    response_model=RestaurantSuggestionOutCount,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(RoleChecker(["moderator"]))],
)
def fetch_count_suggestions(
    db: Session = Depends(get_db),
    filter_params: RestaurantSuggestionFilters = Depends(),
) -> RestaurantSuggestionOutCount:
    """
    Count the suggestions matching the filters (moderators only).

    Parameters:
        db (Session): The database session.
        filter_params (RestaurantSuggestionFilters): The filters parameters.

    Returns:
        RestaurantSuggestionOutCount: The total count.
    """
    return {"total": restaurant_edit_suggestion_crud.count(
        db, **filter_params.model_dump(exclude_none=True))}


@router.get(
    "/search",
    response_model=RestaurantSuggestionOutPaginated,
    status_code=status.HTTP_200_OK,
)
def fetch_suggestions(
    db: Session = Depends(get_db),
    pagination_params: Tuple[int, int] = Depends(get_pagination_params),
    orderby_params: Tuple[str, bool] = Depends(get_sort_by_params),
    filter_params: RestaurantSuggestionFilters = Depends(),
    current_user: User = Depends(get_current_active_user),
) -> RestaurantSuggestionOutPaginated:
    """
    Search suggestions with filters and pagination. Moderators see them
    all, users only their own ones.

    Parameters:
        db (Session): The database session.
        pagination_params (Tuple[int, int]): Pagination (skip, limit).
        orderby_params (Tuple[str, bool]): Sorting (field, descending).
        filter_params (RestaurantSuggestionFilters): Filter parameters.
        current_user (User): The current authenticated user.

    Returns:
        RestaurantSuggestionOutPaginated: Paginated list of suggestions.
    """
    skip, size = pagination_params
    sortby, descending = orderby_params
    filters = filter_params.model_dump(exclude_none=True)
    if not _is_moderator(current_user):
        filters["user_id"] = current_user.id
    suggestions, total = restaurant_edit_suggestion_crud.get_many(
        db,
        skip=skip,
        limit=size,
        order_by=sortby,
        descending=descending,
        **filters
    )
    pages = (total + size - 1) // size
    return {
        "items": [_out(db, suggestion) for suggestion in suggestions],
        "total": total,
        "page": skip // size + 1,
        "size": size,
        "pages": pages,
    }


@router.get(
    "/{id}",
    response_model=RestaurantSuggestionOut,
    status_code=status.HTTP_200_OK,
)
def fetch_suggestion(
    id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> RestaurantSuggestionOut:
    """
    Fetch a suggestion by ID: its author or a moderator.

    Parameters:
        id (int): The suggestion ID.
        db (Session): The database session.
        current_user (User): The current authenticated user.

    Returns:
        RestaurantSuggestionOut: The suggestion.
    """
    return _out(db, _get_suggestion(db, id, current_user))


@router.post(
    "/",
    response_model=RestaurantSuggestionOut,
    status_code=status.HTTP_201_CREATED,
)
def create_suggestion(
    suggestion_in: RestaurantSuggestionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> RestaurantSuggestionOut:
    """
    Suggest a change of a validated restaurant: an edit (fields and/or
    outdated photos to remove), "no vegan option anymore", or a duplicate.
    It replaces the user's pending suggestion for the same restaurant.

    An edit is checked against the business rules on the restaurant as it
    would be, and only keeps the fields it really changes.

    Parameters:
        suggestion_in (RestaurantSuggestionCreate): The suggestion.
        db (Session): The database session.
        current_user (User): The current authenticated user.

    Returns:
        RestaurantSuggestionOut: The created suggestion.
    """
    restaurant = _get_listed_restaurant(db, suggestion_in.restaurant_id)
    suggestion = RestaurantEditSuggestion(
        restaurant_id=restaurant.id,
        user_id=current_user.id,
        kind=suggestion_in.kind,
        comment=(suggestion_in.comment or "").strip() or None,
    )

    if suggestion_in.kind == RestaurantEditSuggestionKind.EDIT:
        try:
            change = compute_restaurant_change(restaurant, suggestion_in.changes)
        except ValidationError as e:
            raise _validation_error(e)
        photos = _removable_photos(db, restaurant.id, suggestion_in.remove_photo_ids)
        if len(photos) != len(set(suggestion_in.remove_photo_ids)):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only the restaurant's approved place and menu photos can be removed",
            )
        changes, base_values = dict(change.after), dict(change.before)
        if photos:
            photo_ids = sorted(photo.id for photo in photos)
            changes[REMOVE_PHOTO_IDS] = photo_ids
            base_values[REMOVE_PHOTO_IDS] = photo_ids
        featured_id = suggestion_in.featured_photo_id
        if featured_id is not None:
            if not _removable_photos(db, restaurant.id, [featured_id]):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Only an approved place or menu photo of the restaurant can be featured",
                )
            # Already the one shown first: nothing to change
            current_id = _featured_photo_id(restaurant)
            if featured_id != current_id:
                changes[FEATURED_PHOTO_ID] = featured_id
                base_values[FEATURED_PHOTO_ID] = current_id
        if not changes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="These are already the restaurant's values",
            )
        suggestion.changes = changes
        suggestion.base_values = base_values

    if suggestion_in.kind == RestaurantEditSuggestionKind.DUPLICATE:
        suggestion.duplicate_of_id = _get_listed_restaurant(
            db, suggestion_in.duplicate_of_id).id

    suggestion = restaurant_edit_suggestion_crud.replace_pending(db, suggestion)
    log.info(
        f"Restaurant suggestion created: {suggestion.kind.value} on restaurant {restaurant.id} by user {current_user.id}")
    return _out(db, suggestion)


@router.delete(
    "/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_suggestion(
    id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """
    Withdraw one's own suggestion while it is pending.

    Parameters:
        id (int): The suggestion ID.
        db (Session): The database session.
        current_user (User): The current authenticated user.
    """
    suggestion = _get_pending_suggestion(db, id, current_user)
    if suggestion.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only withdraw your own suggestions",
        )
    restaurant_edit_suggestion_crud.delete(db, suggestion)
    log.info(f"Restaurant suggestion withdrawn: {id} by user {current_user.id}")


@router.post(
    "/{id}/apply",
    response_model=RestaurantSuggestionOut,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(RoleChecker(["moderator"]))],
)
def apply_suggestion(
    id: int,
    apply_in: RestaurantSuggestionApply,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> RestaurantSuggestionOut:
    """
    Apply a suggestion (moderators only) and record it in the restaurant
    history:
    - an edit: the chosen fields (all by default), with values possibly
      retouched; anything less than the whole edit as proposed makes it
      partially approved;
    - no vegan option anymore: the restaurant is delisted (soft-deleted);
    - a duplicate: its reviews and photos move to the restaurant it
      duplicates, then it is delisted.

    Parameters:
        id (int): The suggestion ID.
        apply_in (RestaurantSuggestionApply): The fields and values to apply.
        db (Session): The database session.
        current_user (User): The current moderator.

    Returns:
        RestaurantSuggestionOut: The reviewed suggestion.
    """
    suggestion = _get_pending_suggestion(db, id, current_user)
    restaurant = restaurant_crud.get_by_id(db, suggestion.restaurant_id)
    if restaurant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found"
        )
    now = datetime.now(timezone.utc)
    final_status = RestaurantEditSuggestionStatus.APPROVED
    paths_to_delete = []

    if suggestion.kind == RestaurantEditSuggestionKind.EDIT:
        proposed = suggestion.changes or {}
        fields = apply_in.fields if apply_in.fields is not None else list(proposed)
        unknown = set(fields) - set(proposed)
        if unknown or not fields:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Choose fields among the proposed ones (or reject the suggestion)",
            )
        field_changes = {
            field: apply_in.values.get(field, proposed[field])
            for field in fields if field not in (REMOVE_PHOTO_IDS, FEATURED_PHOTO_ID)
        }
        try:
            values, before, after = compute_restaurant_change(restaurant, field_changes)
        except ValidationError as e:
            raise _validation_error(e)
        photos = _removable_photos(db, restaurant.id, proposed.get(REMOVE_PHOTO_IDS)) \
            if REMOVE_PHOTO_IDS in fields else []
        featured = None
        if FEATURED_PHOTO_ID in fields:
            candidates = _removable_photos(db, restaurant.id, [proposed[FEATURED_PHOTO_ID]])
            # Gone, or removed by this very suggestion: nothing to feature
            if candidates and candidates[0] not in photos:
                featured = candidates[0]
        if not values and not photos and featured is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Nothing left to apply: these are already the restaurant's values",
            )
        if featured is not None:
            before[FEATURED_PHOTO_ID] = _featured_photo_id(restaurant)
            after[FEATURED_PHOTO_ID] = featured.id
            db.query(RestaurantPhoto).filter(
                RestaurantPhoto.restaurant_id == restaurant.id,
                RestaurantPhoto.is_featured.is_(True),
            ).update({"is_featured": False})
            # Unique index: the previous one must be cleared first
            db.flush()
            featured.is_featured = True
        if photos:
            before["removed_photos"] = sorted(photo.path for photo in photos)
            after["removed_photos"] = []
            paths_to_delete = [photo.path for photo in photos]
            for photo in photos:
                db.delete(photo)
        applied = {**after, **({REMOVE_PHOTO_IDS: sorted(p.id for p in photos)} if photos else {})}
        applied.pop("removed_photos", None)
        if set(fields) != set(proposed) or any(
            field in apply_in.values and apply_in.values[field] != proposed[field]
            for field in fields
        ):
            final_status = RestaurantEditSuggestionStatus.PARTIALLY_APPROVED

    elif suggestion.kind == RestaurantEditSuggestionKind.NO_VEGAN_OPTION:
        values = {"date_deleted": now}
        before = {"date_deleted": None}
        after = {"date_deleted": now.isoformat()}
        applied = {"delisted": True}

    else:  # DUPLICATE
        target = restaurant_crud.get_by_id(db, suggestion.duplicate_of_id or 0)
        if target is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="The restaurant it duplicates no longer exists",
            )
        paths_to_delete = restaurant_edit_suggestion_crud.merge_into(db, restaurant, target)
        values = {"date_deleted": now}
        before = {"date_deleted": None}
        after = {"date_deleted": now.isoformat(), "merged_into": target.id}
        applied = {"merged_into": target.id}

    restaurant_crud.update_with_history(
        db, restaurant, values, before, after,
        user_id=current_user.id, suggestion_id=suggestion.id)
    for path in paths_to_delete:
        s3_file_manager.delete_file(path)
    suggestion = restaurant_edit_suggestion_crud.mark_reviewed(
        db, suggestion, final_status, current_user.id, applied_changes=applied)
    log.info(
        f"Restaurant suggestion {id} {final_status.value} by moderator {current_user.id}")
    return _out(db, suggestion)


@router.post(
    "/{id}/reject",
    response_model=RestaurantSuggestionOut,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(RoleChecker(["moderator"]))],
)
def reject_suggestion(
    id: int,
    reject_in: RestaurantSuggestionReject,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> RestaurantSuggestionOut:
    """
    Reject a suggestion, with an optional reason (moderators only).

    Parameters:
        id (int): The suggestion ID.
        reject_in (RestaurantSuggestionReject): The reason.
        db (Session): The database session.
        current_user (User): The current moderator.

    Returns:
        RestaurantSuggestionOut: The rejected suggestion.
    """
    suggestion = _get_pending_suggestion(db, id, current_user)
    suggestion = restaurant_edit_suggestion_crud.mark_reviewed(
        db, suggestion, RestaurantEditSuggestionStatus.REJECTED, current_user.id,
        rejection_reason=(reject_in.rejection_reason or "").strip() or None)
    log.info(f"Restaurant suggestion {id} rejected by moderator {current_user.id}")
    return _out(db, suggestion)
