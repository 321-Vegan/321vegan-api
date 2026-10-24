import uuid
from pathlib import Path
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.routes.dependencies import get_current_active_user, get_pagination_params, get_sort_by_params, RoleChecker
from app.crud.restaurant import restaurant_crud, restaurant_photo_crud
from app.crud.restaurant_review import restaurant_review_crud
from app.database.db import get_db
from app.log import get_logger
from app.models import User
from app.models.user import UserRole
from app.models.restaurant_photo import RestaurantPhoto, RestaurantPhotoStatus
from app.models.restaurant_review import RestaurantReview, RestaurantReviewStatus
from app.services.s3_file_manager import s3_file_manager
from app.schemas.restaurant import RestaurantPhotoOut
from app.schemas.restaurant_review import (
    RestaurantReviewCreate,
    RestaurantReviewUpdate,
    RestaurantReviewStatusUpdate,
    RestaurantReviewOut,
    RestaurantReviewOutPaginated,
    RestaurantReviewFilters,
    RestaurantReviewSummaryOut,
    RestaurantReviewOutCount,
)

log = get_logger(__name__)

router = APIRouter(dependencies=[Depends(get_current_active_user)])

MAX_PHOTOS_PER_REVIEW = 5


def _clean_comment(comment: Optional[str]) -> Optional[str]:
    """Strip the comment and turn an empty one into None."""
    if comment is None:
        return None
    comment = comment.strip()
    return comment or None


def _status_for(comment: Optional[str], has_photos: bool) -> RestaurantReviewStatus:
    """Ratings alone have nothing to moderate: approve them directly."""
    if comment or has_photos:
        return RestaurantReviewStatus.PENDING
    return RestaurantReviewStatus.APPROVED


def _is_moderator(user: User) -> bool:
    return user.has_role(UserRole.CONTRIBUTOR)


def _visible_filters(filter_params: RestaurantReviewFilters, user: User) -> dict:
    """
    Non-moderator users can only see approved reviews, except their own ones.
    """
    filters = filter_params.model_dump(exclude_none=True)
    own = filters.get("user_id") == user.id
    if not _is_moderator(user) and not own:
        filters.pop("status__ne", None)
        filters["status"] = RestaurantReviewStatus.APPROVED.value
    return filters


def _can_see(review: RestaurantReview, user: User) -> bool:
    return (
        review.status == RestaurantReviewStatus.APPROVED
        or review.user_id == user.id
        or _is_moderator(user)
    )


def _get_own_review(db: Session, id: int, user: User) -> RestaurantReview:
    """
    Raises:
        HTTPException: If the review does not exist or is not the user's.
    """
    review = restaurant_review_crud.get_by_id(db, id)
    if review is None or not _can_see(review, user):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Review not found"
        )
    if review.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You can only edit your own reviews"
        )
    return review


@router.get(
    "/count",
    response_model=Optional[RestaurantReviewOutCount],
    status_code=status.HTTP_200_OK,
)
def fetch_count_restaurant_reviews(
    db: Session = Depends(get_db),
    filter_params: RestaurantReviewFilters = Depends(),
    current_user: User = Depends(get_current_active_user),
) -> Optional[RestaurantReviewOutCount]:
    """
    Fetch how many restaurant reviews match the filters.

    Parameters:
        db (Session): The database session.
        filter_params (RestaurantReviewFilters): The filters parameters.
        current_user (User): The current authenticated user.

    Returns:
        Optional[RestaurantReviewOutCount]: The total count of matching reviews.
    """
    total = restaurant_review_crud.count(
        db,
        **_visible_filters(filter_params, current_user)
    )
    return {
        "total": total
    }


@router.post(
    "/",
    response_model=RestaurantReviewOut,
    status_code=status.HTTP_201_CREATED,
)
def create_review(
    review_in: RestaurantReviewCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> RestaurantReviewOut:
    """
    Create a restaurant review. One review per user per restaurant, on a
    validated restaurant only.

    A review with a comment (or photos, added afterwards) is pending until
    moderated; ratings alone are approved directly.

    Parameters:
        review_in (RestaurantReviewCreate): The review data.
        db (Session): The database session.
        current_user (User): The current authenticated user.

    Returns:
        RestaurantReviewOut: The created review.
    """
    restaurant = restaurant_crud.get_by_id(db, review_in.restaurant_id)
    if restaurant is None or not restaurant.validated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found"
        )

    review_in.user_id = current_user.id
    review_in.comment = _clean_comment(review_in.comment)
    review_in.status = _status_for(review_in.comment, has_photos=False)
    try:
        review = restaurant_review_crud.create(db, review_in)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already reviewed this restaurant",
        )

    log.info(
        f"Restaurant review created: restaurant {review_in.restaurant_id} by user {current_user.id}")
    return review


@router.get(
    "/search", response_model=Optional[RestaurantReviewOutPaginated], status_code=status.HTTP_200_OK,
)
def fetch_reviews(
    db: Session = Depends(get_db),
    pagination_params: Tuple[int, int] = Depends(get_pagination_params),
    orderby_params: Tuple[str, bool] = Depends(get_sort_by_params),
    filter_params: RestaurantReviewFilters = Depends(),
    current_user: User = Depends(get_current_active_user),
) -> RestaurantReviewOutPaginated:
    """
    Search reviews with filters and pagination.

    Non-moderator users only get approved reviews, except when filtering
    on their own user_id (to display their profile).
    Moderators (contributors and admins) can filter by status=PENDING for moderation.

    Parameters:
        db (Session): The database session.
        pagination_params (Tuple[int, int]): Pagination (skip, limit).
        orderby_params (Tuple[str, bool]): Sorting (field, descending).
        filter_params (RestaurantReviewFilters): Filter parameters.
        current_user (User): The current authenticated user.

    Returns:
        RestaurantReviewOutPaginated: Paginated list of reviews.
    """
    skip, size = pagination_params
    sortby, descending = orderby_params
    reviews, total = restaurant_review_crud.get_many(
        db,
        skip=skip,
        limit=size,
        order_by=sortby,
        descending=descending,
        **_visible_filters(filter_params, current_user)
    )
    pages = (total + size - 1) // size
    return {
        "items": reviews,
        "total": total,
        "page": skip // size + 1,
        "size": size,
        "pages": pages,
    }


@router.get(
    "/restaurants/{restaurant_id}/summary",
    response_model=RestaurantReviewSummaryOut,
    status_code=status.HTTP_200_OK,
)
def fetch_restaurant_review_summary(
    restaurant_id: int,
    db: Session = Depends(get_db),
) -> RestaurantReviewSummaryOut:
    """
    Fetch aggregated review stats for a restaurant (approved reviews only):
    the overall rating with its distribution, and each detailed rating.

    Parameters:
        restaurant_id (int): The restaurant ID.
        db (Session): The database session.

    Returns:
        RestaurantReviewSummaryOut: Review count, ratings and distribution.
    """
    return restaurant_review_crud.get_restaurant_summary(db, restaurant_id)


@router.get(
    "/{id}",
    response_model=RestaurantReviewOut,
    status_code=status.HTTP_200_OK,
)
def fetch_review_by_id(
    id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> RestaurantReviewOut:
    """
    Fetch a review by ID.

    Parameters:
        id (int): The review ID.
        db (Session): The database session.
        current_user (User): The current authenticated user.

    Returns:
        RestaurantReviewOut: The review.
    """
    review = restaurant_review_crud.get_by_id(db, id)
    if review is None or not _can_see(review, current_user):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Review not found"
        )
    return review


@router.put(
    "/{id}",
    response_model=RestaurantReviewOut,
    status_code=status.HTTP_200_OK,
)
def update_review(
    id: int,
    review_in: RestaurantReviewUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> RestaurantReviewOut:
    """
    Update a restaurant review. A changed comment goes back to moderation;
    changed ratings alone keep the current status.

    Parameters:
        id (int): The review ID.
        review_in (RestaurantReviewUpdate): The updated review data.
        db (Session): The database session.
        current_user (User): The current authenticated user.

    Returns:
        RestaurantReviewOut: The updated review.
    """
    review = _get_own_review(db, id, current_user)

    changes = review_in.model_dump(exclude_unset=True)
    if changes.get("rating", 0) is None:
        # The overall rating is required, it cannot be cleared
        changes.pop("rating")
    comment_changed = False
    if "comment" in changes:
        changes["comment"] = _clean_comment(changes["comment"])
        comment_changed = changes["comment"] != review.comment
    for field, value in changes.items():
        setattr(review, field, value)

    new_status = _status_for(review.comment, bool(review.photos)) \
        if comment_changed else review.status
    updated_review = restaurant_review_crud.set_status(db, review, new_status)
    log.info(f"Restaurant review updated: {id} by user {current_user.id}")
    return updated_review


@router.delete(
    "/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_review(
    id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """
    Delete a restaurant review and its photos. Author or moderator
    (contributor or admin) only.

    Parameters:
        id (int): The review ID.
        db (Session): The database session.
        current_user (User): The current authenticated user.
    """
    review = restaurant_review_crud.get_by_id(db, id)
    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Review not found"
        )
    if review.user_id != current_user.id and not _is_moderator(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You can only delete your own reviews"
        )

    paths = [photo.path for photo in review.photos]
    restaurant_review_crud.delete(db, review)
    for path in paths:
        s3_file_manager.delete_file(path)
    log.info(f"Restaurant review deleted: {id} by user {current_user.id}")


@router.patch(
    "/{id}/status",
    response_model=RestaurantReviewOut,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(RoleChecker(["contributor", "admin"]))]
)
def update_review_status(
    id: int,
    status_in: RestaurantReviewStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> RestaurantReviewOut:
    """
    Approve or reject a review and its photos (contributor or admin only).

    Parameters:
        id (int): The review ID.
        status_in (RestaurantReviewStatusUpdate): The new status.
        db (Session): The database session.
        current_user (User): The current moderator user.

    Returns:
        RestaurantReviewOut: The updated review.
    """
    review = restaurant_review_crud.get_by_id(db, id)
    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Review not found"
        )

    updated_review = restaurant_review_crud.set_status(
        db, review, status_in.status)
    log.info(
        f"Restaurant review {id} status updated to {status_in.status} by moderator {current_user.id}")
    return updated_review


@router.post(
    "/{id}/photos",
    response_model=RestaurantPhotoOut,
    status_code=status.HTTP_201_CREATED,
)
def upload_review_photo(
    id: int,
    file: UploadFile = File(...,
                            description="Image (JPG, PNG, WebP max 5MB)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> RestaurantPhotoOut:
    """
    Add a photo to one's own review. It is stored in the bucket under
    restaurants/{restaurant_id}/reviews/, and the review goes back to
    moderation.

    Parameters:
        id (int): The review ID.
        file (UploadFile): Image file (JPG, PNG, WebP, max 5MB).
        db (Session): The database session.
        current_user (User): The current authenticated user.

    Returns:
        RestaurantPhotoOut: The created photo.
    """
    review = _get_own_review(db, id, current_user)
    if len(review.photos) >= MAX_PHOTOS_PER_REVIEW:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"A review cannot have more than {MAX_PHOTOS_PER_REVIEW} photos",
        )

    file_extension = Path(file.filename or "").suffix.lower()
    object_name = f"restaurants/{review.restaurant_id}/reviews/{review.id}_{uuid.uuid4().hex}{file_extension}"
    s3_file_manager.upload_image(object_name, file)

    photo = RestaurantPhoto(
        restaurant_id=review.restaurant_id,
        review_id=review.id,
        path=object_name,
        status=RestaurantPhotoStatus.PENDING,
        user_id=current_user.id,
    )
    try:
        db.add(photo)
        db.flush()
        db.refresh(review)
        restaurant_review_crud.set_status(
            db, review, RestaurantReviewStatus.PENDING)
        db.refresh(photo)
    except IntegrityError as e:
        db.rollback()
        s3_file_manager.delete_file(object_name)
        log.error(f"Error saving restaurant review photo: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Error saving photo",
        )
    log.info(
        f"Restaurant review photo added: {object_name} (ID: {photo.id}) by user {current_user.id}")
    return photo


@router.delete(
    "/{id}/photos/{photo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_review_photo(
    id: int,
    photo_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """
    Delete a review photo. Its author or a moderator only. When the author
    removes the last thing left to moderate, the review is approved again.

    Parameters:
        id (int): The review ID.
        photo_id (int): The photo ID.
        db (Session): The database session.
        current_user (User): The current authenticated user.
    """
    photo = restaurant_photo_crud.get_by_id(db, photo_id)
    if photo is None or photo.review_id != id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Photo not found"
        )
    review = photo.review
    if review.user_id != current_user.id and not _is_moderator(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete your own photos",
        )

    path = photo.path
    restaurant_photo_crud.delete(db, photo)
    s3_file_manager.delete_file(path)
    db.refresh(review)
    if (review.user_id == current_user.id
            and review.status == RestaurantReviewStatus.PENDING
            and _status_for(review.comment, bool(review.photos)) == RestaurantReviewStatus.APPROVED):
        restaurant_review_crud.set_status(
            db, review, RestaurantReviewStatus.APPROVED)
    log.info(
        f"Restaurant review photo deleted: {photo_id} by user {current_user.id}")
