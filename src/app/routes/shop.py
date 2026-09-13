from typing import List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.routes.dependencies import get_current_active_user, get_pagination_params, get_sort_by_params, RoleChecker
from app.crud.shop import shop_crud
from app.database.db import get_db
from app.log import get_logger
from app.models import Shop, User
from app.schemas.shop import ShopCreate, ShopOut, ShopUpdate, ShopOutPaginated, ShopFilters, ShopScanSummaryOut

log = get_logger(__name__)

router = APIRouter(dependencies=[Depends(get_current_active_user)])


@router.get(
    "/", response_model=List[Optional[ShopOut]], status_code=status.HTTP_200_OK
)
def fetch_all_shops(db: Session = Depends(get_db)) -> List[Optional[ShopOut]]:
    """
    Fetch all shops.

    Parameters:
        db (Session): The database session.

    Returns:
        List[Optional[ShopOut]]: The list of shops fetched from the database.
    """
    return shop_crud.get_all(db)


@router.get(
    "/search", response_model=Optional[ShopOutPaginated], status_code=status.HTTP_200_OK
)
def fetch_paginated_shops(
    filter_params: ShopFilters = Depends(),
    ean__in: Optional[List[str]] = Query(default=None),
    min_lat: Optional[float] = Query(default=None, ge=-90, le=90),
    max_lat: Optional[float] = Query(default=None, ge=-90, le=90),
    min_lng: Optional[float] = Query(default=None, ge=-180, le=180),
    max_lng: Optional[float] = Query(default=None, ge=-180, le=180),
    db: Session = Depends(get_db),
    pagination_params: Tuple[int, int] = Depends(get_pagination_params),
    orderby_params: Tuple[str, bool] = Depends(get_sort_by_params),
) -> Optional[ShopOutPaginated]:
    """
    Fetch many shops with pagination and filters.

    Parameters:
        filter_params (ShopFilters): Filter parameters (name, city, country, shop_type).
        ean__in (List[str]): EAN codes to filter by. Supports repeated params or comma-separated values.
        min_lat/max_lat/min_lng/max_lng (float): Bounding box to restrict results geographically.
        db (Session): The database session.
        pagination_params (Tuple[int, int]): The pagination parameters (skip, limit).
        orderby_params (Tuple[str, bool]): The order by parameters (sortby, descending).

    Returns:
        ShopOutPaginated: The list of shops with pagination data.
    """
    page, size = pagination_params
    sortby, descending = orderby_params
    filters = filter_params.model_dump(exclude_none=True)
    if 'validated' not in filters:
        filters['validated'] = True
    if ean__in:
        eans = []
        for e in ean__in:
            eans.extend(x.strip() for x in e.split(',') if x.strip())
        filters['ean__in'] = eans
    if min_lat is not None:
        filters['latitude__ge'] = min_lat
    if max_lat is not None:
        filters['latitude__le'] = max_lat
    if min_lng is not None:
        filters['longitude__ge'] = min_lng
    if max_lng is not None:
        filters['longitude__le'] = max_lng
    shops, total = shop_crud.get_many(
        db,
        skip=page,
        limit=size,
        order_by=sortby,
        descending=descending,
        filters=filters
    )
    pages = (total + size - 1) // size
    return {
        "items": shops,
        "total": total,
        "page": page,
        "size": size,
        "pages": pages
    }


@router.get(
    "/in-area", response_model=List[ShopOut], status_code=status.HTTP_200_OK
)
def fetch_shops_in_area(
    min_lat: float = Query(..., ge=-90, le=90),
    max_lat: float = Query(..., ge=-90, le=90),
    min_lng: float = Query(..., ge=-180, le=180),
    max_lng: float = Query(..., ge=-180, le=180),
    db: Session = Depends(get_db),
) -> List[ShopOut]:
    """
    Fetch shops within a geographic bounding box.

    Parameters:
        min_lat (float): Minimum latitude of the bounding box.
        max_lat (float): Maximum latitude of the bounding box.
        min_lng (float): Minimum longitude of the bounding box.
        max_lng (float): Maximum longitude of the bounding box.
        db (Session): The database session.

    Returns:
        List[ShopOut]: The list of shops within the bounding box (max 300).
    """
    return shop_crud.get_in_bounding_box(db, min_lat, max_lat, min_lng, max_lng)


@router.get(
    "/{id}/products", response_model=List[ShopScanSummaryOut], status_code=status.HTTP_200_OK
)
def fetch_shop_products(
    id: int, db: Session = Depends(get_db)
) -> List[ShopScanSummaryOut]:
    """
    Fetch products of interest scanned at a shop.

    Returns distinct EANs with scan count and last scan date.

    Parameters:
        id (int): The ID of the shop.
        db (Session): The database session.

    Returns:
        List[ShopScanSummaryOut]: The scan summary for products at this shop.
    """
    shop = shop_crud.get_by_id(db, id)
    if shop is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Shop not found"
        )
    return shop_crud.get_shop_scan_summary(db, id)


@router.get(
    "/{id}",
    response_model=Optional[ShopOut],
    status_code=status.HTTP_200_OK,
)
def fetch_shop_by_id(
    id: int, db: Session = Depends(get_db)
) -> ShopOut:
    """
    Fetches a shop by its ID.

    Parameters:
        id (int): The ID of the shop.
        db (Session): The database session.

    Returns:
        ShopOut: The shop fetched from the database.
    """
    shop = shop_crud.get_by_id(db, id)
    if shop is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Shop not found"
        )
    return shop


@router.post(
    "/", response_model=ShopOut, status_code=status.HTTP_201_CREATED
)
def create_shop(
    shop_in: ShopCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
) -> ShopOut:
    """
    Create a new shop. Any authenticated user can submit a shop.
    The created_by field is automatically set to the current user's ID,
    and the shop is left unvalidated until an admin reviews it.

    Parameters:
        shop_in (ShopCreate): The shop data.
        db (Session): The database session.
        current_user (User): The current authenticated user.

    Returns:
        ShopOut: The created shop.
    """
    try:
        shop = shop_crud.create(db, shop_in)
        shop.created_by = current_user.id
        shop.validated = False
        db.commit()
        db.refresh(shop)
        log.info(f"Shop created: {shop.name} (ID: {shop.id}) by user {current_user.id}")
        return shop
    except IntegrityError as e:
        db.rollback()
        log.error(f"Error creating shop: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Shop with this OSM ID already exists"
        )


@router.put(
    "/{id}",
    response_model=ShopOut,
    status_code=status.HTTP_200_OK,
)
def update_shop(
    id: int,
    shop_in: ShopUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(["admin"]))
) -> ShopOut:
    """
    Update a shop.

    Parameters:
        id (int): The ID of the shop.
        shop_in (ShopUpdate): The updated shop data.
        db (Session): The database session.
        current_user (User): The current authenticated user.

    Returns:
        ShopOut: The updated shop.
    """
    shop = shop_crud.get_by_id(db, id)
    if shop is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Shop not found"
        )

    try:
        updated_shop = shop_crud.update(db, shop, shop_in)
        log.info(f"Shop updated: {updated_shop.name} (ID: {updated_shop.id})")
        return updated_shop
    except IntegrityError as e:
        db.rollback()
        log.error(f"Error updating shop: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Error updating shop"
        )


@router.delete(
    "/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_shop(
    id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(RoleChecker(["admin"]))
) -> None:
    """
    Soft-delete a shop: sets date_deleted instead of removing the row, so its
    scan/review history is preserved.

    Parameters:
        id (int): The ID of the shop.
        db (Session): The database session.
        current_user (User): The current authenticated user.
    """
    shop = shop_crud.get_by_id(db, id)
    if shop is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Shop not found"
        )

    shop_crud.soft_delete(db, shop)
    log.info(f"Shop soft-deleted: ID {id}")
