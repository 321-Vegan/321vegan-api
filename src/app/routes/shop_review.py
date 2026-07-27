from typing import Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.routes.dependencies import get_current_active_user, get_pagination_params, get_sort_by_params, RoleChecker
from app.crud.shop import shop_crud
from app.crud.shop_review import shop_review_crud
from app.database.db import get_db
from app.log import get_logger
from app.models import User
from app.models.shop_review import ShopReviewStatus
from app.services.xp_service import award_xp, XPAction
from app.schemas.shop_review import (
    ShopReviewCreate,
    ShopReviewUpdate,
    ShopReviewStatusUpdate,
    ShopReviewOut,
    ShopReviewOutPaginated,
    ShopReviewFilters,
    ShopReviewSummaryOut,
    ShopReviewOutCount
)

log = get_logger(__name__)

router = APIRouter(dependencies=[Depends(get_current_active_user)])


@router.get(
    "/count",
    response_model=Optional[ShopReviewOutCount],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(get_current_active_user)]
)
def fetch_count_shop_reviews(
    db: Session = Depends(get_db),
    filter_params: ShopReviewFilters = Depends(),
) -> Optional[ShopReviewOutCount]:
    """
    Fetch how many shop reviews.

    This function fetches total shop review count from the
    database based on the filters parameters.

    Parameters:
        db (Session): The database session.
        filter_params (ShopReviewFilters): The filters parameters.

    Returns:
        Optional[ShopReviewOutCount]: The total count of shop reviews fetched from the database with filter datas.
    """
    total = shop_review_crud.count(
        db,
        **filter_params.model_dump(exclude_none=True)
    )
    return {
        "total": total
    }


@router.post(
    "/",
    response_model=ShopReviewOut,
    status_code=status.HTTP_201_CREATED,
)
def create_review(
    review_in: ShopReviewCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ShopReviewOut:
    """
    Create a shop review. One review per user per shop.

    Parameters:
        review_in (ShopReviewCreate): The review data.
        db (Session): The database session.
        current_user (User): The current authenticated user.

    Returns:
        ShopReviewOut: The created review.
    """
    shop = shop_crud.get_by_id(db, review_in.shop_id)
    if shop is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Shop not found"
        )

    review_in.user_id = current_user.id
    try:
        review = shop_review_crud.create(db, review_in)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already reviewed this shop",
        )

    xp_awarded = award_xp(
        db, current_user, XPAction.SHOP_REVIEW,
        reference_type="shop_review", reference_id=review.id,
    )
    review.xp_awarded = xp_awarded

    log.info(
        f"Shop review created: shop {review_in.shop_id} by user {current_user.id}")
    return review


@router.get(
    "/search", response_model=Optional[ShopReviewOutPaginated], status_code=status.HTTP_200_OK,
)
def fetch_reviews(
    db: Session = Depends(get_db),
    pagination_params: Tuple[int, int] = Depends(get_pagination_params),
    orderby_params: Tuple[str, bool] = Depends(get_sort_by_params),
    filter_params: ShopReviewFilters = Depends(),
) -> ShopReviewOutPaginated:
    """
    Search reviews with filters and pagination.

    Filterable by shop_id, user_id, status.
    Admins can filter by status=PENDING for moderation.

    Parameters:
        filter_params (ShopReviewFilters): Filter parameters.
        db (Session): The database session.
        pagination_params (Tuple[int, int]): Pagination (skip, limit).
        orderby_params (Tuple[str, bool]): Sorting (field, descending).

    Returns:
        ShopReviewOutPaginated: Paginated list of reviews.
    """
    page, size = pagination_params
    sortby, descending = orderby_params
    reviews, total = shop_review_crud.get_many(
        db,
        skip=page,
        limit=size,
        order_by=sortby,
        descending=descending,
        **filter_params.model_dump(exclude_none=True)
    )
    pages = (total + size - 1) // size
    return {
        "items": reviews,
        "total": total,
        "page": page,
        "size": size,
        "pages": pages,
    }


@router.get(
    "/shops/{shop_id}/summary",
    response_model=ShopReviewSummaryOut,
    status_code=status.HTTP_200_OK,
)
def fetch_shop_review_summary(
    shop_id: int,
    db: Session = Depends(get_db),
) -> ShopReviewSummaryOut:
    """
    Fetch aggregated review stats for a shop (approved reviews only).

    Parameters:
        shop_id (int): The shop ID.
        db (Session): The database session.

    Returns:
        ShopReviewSummaryOut: Review count and average rating.
    """
    return shop_review_crud.get_shop_summary(db, shop_id)


@router.get(
    "/{id}",
    response_model=ShopReviewOut,
    status_code=status.HTTP_200_OK,
)
def fetch_review_by_id(
    id: int,
    db: Session = Depends(get_db),
) -> ShopReviewOut:
    """
    Fetch a review by ID.

    Parameters:
        id (int): The review ID.
        db (Session): The database session.

    Returns:
        ShopReviewOut: The review.
    """
    review = shop_review_crud.get_by_id(db, id)
    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Review not found"
        )
    return review


@router.put(
    "/{id}",
    response_model=ShopReviewOut,
    status_code=status.HTTP_200_OK,
)
def update_review(
    id: int,
    review_in: ShopReviewUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ShopReviewOut:
    """
    Update a shop review. Resets status to pending for re-moderation.

    Parameters:
        id (int): The review ID.
        review_in (ShopReviewUpdate): The updated review data.
        db (Session): The database session.
        current_user (User): The current authenticated user.

    Returns:
        ShopReviewOut: The updated review.
    """
    review = shop_review_crud.get_by_id(db, id)
    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Review not found"
        )
    if review.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You can only edit your own reviews"
        )

    dict_review_update = review_in.model_dump()
    dict_review_update['status'] = ShopReviewStatus.PENDING
    review_update = ShopReviewUpdate(
        **dict_review_update,
    )
    updated_review = shop_review_crud.update(db, review, review_update)
    log.info(f"Shop review updated: {id} by user {current_user.id}")
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
    Delete a shop review. Author or admin only.

    Parameters:
        id (int): The review ID.
        db (Session): The database session.
        current_user (User): The current authenticated user.
    """
    review = shop_review_crud.get_by_id(db, id)
    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Review not found"
        )
    if review.user_id != current_user.id:
        if not current_user.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="You can only delete your own reviews"
            )

    shop_review_crud.delete(db, review)
    log.info(f"Shop review deleted: {id} by user {current_user.id}")


@router.patch(
    "/{id}/status",
    response_model=ShopReviewOut,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(RoleChecker(["admin"]))]
)
def update_review_status(
    id: int,
    status_in: ShopReviewStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ShopReviewOut:
    """
    Approve or reject a review (admin only).

    Parameters:
        id (int): The review ID.
        status_in (ShopReviewStatusUpdate): The new status.
        db (Session): The database session.
        current_user (User): The current admin user.

    Returns:
        ShopReviewOut: The updated review.
    """
    review = shop_review_crud.get_by_id(db, id)
    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Review not found"
        )

    updated_review = shop_review_crud.update(db, review, status_in)
    log.info(
        f"Shop review {id} status updated to {status_in.status} by admin {current_user.id}")
    return updated_review
