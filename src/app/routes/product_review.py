from typing import Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.routes.dependencies import get_current_active_user, get_pagination_params, get_sort_by_params, RoleChecker
from app.crud.product import product_crud
from app.crud.product_review import product_review_crud
from app.database.db import get_db
from app.log import get_logger
from app.models import User, Product
from app.models.product_review import ProductReview, ProductReviewStatus
from app.schemas.product_review import (
    ProductReviewCreate,
    ProductReviewUpdate,
    ProductReviewStatusUpdate,
    ProductReviewOut,
    ProductReviewOutPaginated,
    ProductReviewFilters,
    ProductReviewSummaryOut,
    ProductReviewOutCount
)

log = get_logger(__name__)

router = APIRouter(dependencies=[Depends(get_current_active_user)])


def _clean_comment(comment: Optional[str]) -> Optional[str]:
    """Strip the comment and turn an empty one into None."""
    if comment is None:
        return None
    comment = comment.strip()
    return comment or None


def _status_for_comment(comment: Optional[str]) -> ProductReviewStatus:
    """A rating without comment has nothing to moderate: approve it directly."""
    return ProductReviewStatus.PENDING if comment else ProductReviewStatus.APPROVED


def _visible_filters(filter_params: ProductReviewFilters, current_user: User) -> dict:
    """
    Non-admin users can only see approved reviews, except their own ones.
    """
    filters = filter_params.model_dump(exclude_none=True)
    if not current_user.is_admin() and filters.get("user_id") != current_user.id:
        filters.pop("status__ne", None)
        filters["status"] = ProductReviewStatus.APPROVED.value
    return filters


def _can_see(review: ProductReview, current_user: User) -> bool:
    return (
        review.status == ProductReviewStatus.APPROVED
        or review.user_id == current_user.id
        or current_user.is_admin()
    )


@router.get(
    "/count",
    response_model=Optional[ProductReviewOutCount],
    status_code=status.HTTP_200_OK,
)
def fetch_count_product_reviews(
    db: Session = Depends(get_db),
    filter_params: ProductReviewFilters = Depends(),
    current_user: User = Depends(get_current_active_user),
) -> Optional[ProductReviewOutCount]:
    """
    Fetch how many product reviews.

    This function fetches total product review count from the
    database based on the filters parameters.

    Parameters:
        db (Session): The database session.
        filter_params (ProductReviewFilters): The filters parameters.
        current_user (User): The current authenticated user.

    Returns:
        Optional[ProductReviewOutCount]: The total count of product reviews fetched from the database with filter datas.
    """
    total = product_review_crud.count(
        db,
        **_visible_filters(filter_params, current_user)
    )
    return {
        "total": total
    }


@router.post(
    "/",
    response_model=ProductReviewOut,
    status_code=status.HTTP_201_CREATED,
)
def create_review(
    review_in: ProductReviewCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ProductReviewOut:
    """
    Create a product review. One review per user per product.

    A review with a comment is pending until moderated, a rating
    without comment is approved directly.

    Parameters:
        review_in (ProductReviewCreate): The review data.
        db (Session): The database session.
        current_user (User): The current authenticated user.

    Returns:
        ProductReviewOut: The created review.
    """
    product = product_crud.get_one(db, Product.id == review_in.product_id)
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
        )

    review_in.user_id = current_user.id
    review_in.comment = _clean_comment(review_in.comment)
    review_in.status = _status_for_comment(review_in.comment)
    try:
        review = product_review_crud.create(db, review_in)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already reviewed this product",
        )

    log.info(
        f"Product review created: product {review_in.product_id} by user {current_user.id}")
    return review


@router.get(
    "/search", response_model=Optional[ProductReviewOutPaginated], status_code=status.HTTP_200_OK,
)
def fetch_reviews(
    db: Session = Depends(get_db),
    pagination_params: Tuple[int, int] = Depends(get_pagination_params),
    orderby_params: Tuple[str, bool] = Depends(get_sort_by_params),
    filter_params: ProductReviewFilters = Depends(),
    current_user: User = Depends(get_current_active_user),
) -> ProductReviewOutPaginated:
    """
    Search reviews with filters and pagination.

    Filterable by product_id, product___ean, user_id, status...
    Non-admin users only get approved reviews, except when filtering
    on their own user_id (to display their profile).
    Admins can filter by status=PENDING for moderation.

    Parameters:
        db (Session): The database session.
        pagination_params (Tuple[int, int]): Pagination (skip, limit).
        orderby_params (Tuple[str, bool]): Sorting (field, descending).
        filter_params (ProductReviewFilters): Filter parameters.
        current_user (User): The current authenticated user.

    Returns:
        ProductReviewOutPaginated: Paginated list of reviews.
    """
    skip, size = pagination_params
    sortby, descending = orderby_params
    reviews, total = product_review_crud.get_many(
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
    "/products/{product_id}/summary",
    response_model=ProductReviewSummaryOut,
    status_code=status.HTTP_200_OK,
)
def fetch_product_review_summary(
    product_id: int,
    db: Session = Depends(get_db),
) -> ProductReviewSummaryOut:
    """
    Fetch aggregated review stats for a product (approved reviews only).

    Parameters:
        product_id (int): The product ID.
        db (Session): The database session.

    Returns:
        ProductReviewSummaryOut: Review count, average rating and distribution.
    """
    return product_review_crud.get_product_summary(db, product_id)


@router.get(
    "/products/ean/{ean}/summary",
    response_model=ProductReviewSummaryOut,
    status_code=status.HTTP_200_OK,
)
def fetch_product_review_summary_by_ean(
    ean: str,
    db: Session = Depends(get_db),
) -> ProductReviewSummaryOut:
    """
    Fetch aggregated review stats for a product by its EAN (approved reviews only).
    Useful at scan time when only the EAN is known.

    Parameters:
        ean (str): The product EAN.
        db (Session): The database session.

    Returns:
        ProductReviewSummaryOut: Review count, average rating and distribution.
    """
    product = product_crud.get_one(db, Product.ean == ean)
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
        )
    return product_review_crud.get_product_summary(db, product.id)


@router.get(
    "/{id}",
    response_model=ProductReviewOut,
    status_code=status.HTTP_200_OK,
)
def fetch_review_by_id(
    id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ProductReviewOut:
    """
    Fetch a review by ID.

    Parameters:
        id (int): The review ID.
        db (Session): The database session.
        current_user (User): The current authenticated user.

    Returns:
        ProductReviewOut: The review.
    """
    review = product_review_crud.get_by_id(db, id)
    if review is None or not _can_see(review, current_user):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Review not found"
        )
    return review


@router.put(
    "/{id}",
    response_model=ProductReviewOut,
    status_code=status.HTTP_200_OK,
)
def update_review(
    id: int,
    review_in: ProductReviewUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ProductReviewOut:
    """
    Update a product review. A changed comment goes back to moderation.

    Parameters:
        id (int): The review ID.
        review_in (ProductReviewUpdate): The updated review data.
        db (Session): The database session.
        current_user (User): The current authenticated user.

    Returns:
        ProductReviewOut: The updated review.
    """
    review = product_review_crud.get_by_id(db, id)
    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Review not found"
        )
    if review.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You can only edit your own reviews"
        )

    dict_review_update = review_in.model_dump(exclude_unset=True)
    dict_review_update.pop("status", None)
    if "comment" in dict_review_update:
        comment = _clean_comment(dict_review_update["comment"])
        dict_review_update["comment"] = comment
        if comment != review.comment:
            dict_review_update["status"] = _status_for_comment(comment)
    review_update = ProductReviewUpdate(
        **dict_review_update,
    )
    updated_review = product_review_crud.update(db, review, review_update)
    log.info(f"Product review updated: {id} by user {current_user.id}")
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
    Delete a product review. Author or admin only.

    Parameters:
        id (int): The review ID.
        db (Session): The database session.
        current_user (User): The current authenticated user.
    """
    review = product_review_crud.get_by_id(db, id)
    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Review not found"
        )
    if review.user_id != current_user.id and not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You can only delete your own reviews"
        )

    product_review_crud.delete(db, review)
    log.info(f"Product review deleted: {id} by user {current_user.id}")


@router.patch(
    "/{id}/status",
    response_model=ProductReviewOut,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(RoleChecker(["admin"]))]
)
def update_review_status(
    id: int,
    status_in: ProductReviewStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ProductReviewOut:
    """
    Approve or reject a review (admin only).

    Parameters:
        id (int): The review ID.
        status_in (ProductReviewStatusUpdate): The new status.
        db (Session): The database session.
        current_user (User): The current admin user.

    Returns:
        ProductReviewOut: The updated review.
    """
    review = product_review_crud.get_by_id(db, id)
    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Review not found"
        )

    updated_review = product_review_crud.update(db, review, status_in)
    log.info(
        f"Product review {id} status updated to {status_in.status} by admin {current_user.id}")
    return updated_review
