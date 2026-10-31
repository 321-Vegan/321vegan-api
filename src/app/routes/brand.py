from typing import Annotated, List, Optional, Tuple

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status, File, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.routes.dependencies import get_current_active_user, get_pagination_params, get_sort_by_params, RoleChecker
from app.crud import brand_crud
from app.database.db import get_db
from app.log import get_logger
from app.models import Brand
from app.schemas.brand import BrandCreate, BrandOut, BrandUpdate, BrandOutPaginated, BrandFilters, BrandLookalikeFilter
from app.services.file_service import file_service

log = get_logger(__name__)

router = APIRouter(dependencies=[Depends(get_current_active_user)])


@router.get(
    "/", response_model=List[Optional[BrandOut]], status_code=status.HTTP_200_OK
)
def fetch_all_brands(db: Session = Depends(get_db)) -> List[Optional[BrandOut]]:
    """
    Fetch all brands.

    This function fetches all brands from the
    database.

    Parameters:
        db (Session): The database session.

    Returns:
        BrandOut: The list of brands fetched from the database.
    """

    return brand_crud.get_all(db)


@router.get(
    "/search", response_model=Optional[BrandOutPaginated], status_code=status.HTTP_200_OK
)
def fetch_paginated_brands(
    db: Session = Depends(get_db),
    pagination_params: Tuple[int, int] = Depends(get_pagination_params),
    orderby_params: Tuple[str, bool] = Depends(get_sort_by_params),
    filter_params: BrandFilters = Depends()
) -> Optional[BrandOutPaginated]:
    """
    Fetch many brands.

    This function fetches all brands from the
    database based on the pagination parameters.

    Parameters:
        db (Session): The database session.
        pagination_params (Tuple[int, int]): The pagination parameters (skip, limit).
        orderby_params (Tuple[str, bool]): The order by parameters (sortby, descending).

    Returns:
        BrandOutPaginated: The list of brands fetched from the database with pagination datas.
    """
    page, size = pagination_params
    sortby, descending = orderby_params

    # check if `name__lookalike` is in query
    filter_dict = filter_params.model_dump(exclude_none=True)
    if "name__lookalike" in filter_dict:
        name = filter_dict.pop("name__lookalike")
        brands, total = brand_crud.get_many_ranked(
            db, 'name', name, skip=page, limit=size, **filter_dict
        )
    else:
        brands, total = brand_crud.get_many(
            db,
            skip=page,
            limit=size,
            order_by=sortby,
            descending=descending,
            **filter_dict
        )

    pages = (total + size - 1) // size
    return {
        "items": brands,
        "total": total,
        "page": page,
        "size": size,
        "pages": pages
    }


@router.get(
    "/search/ranked", response_model=Optional[BrandOutPaginated], status_code=status.HTTP_200_OK
)
def fetch_ranked_brands(
    db: Session = Depends(get_db),
    pagination_params: Tuple[int, int] = Depends(get_pagination_params),
    name: str = Query(..., min_length=1),
) -> Optional[BrandOutPaginated]:
    page, size = pagination_params
    brands, total = brand_crud.get_many_ranked(db, 'name', name, skip=page, limit=size)
    pages = (total + size - 1) // size
    return {
        "items": brands,
        "total": total,
        "page": page,
        "size": size,
        "pages": pages
    }


@router.get("/lookalike", response_model=Optional[BrandOut], status_code=status.HTTP_200_OK, dependencies=[Depends(get_current_active_user)])
def fetch_brand_by_name(name_param: BrandLookalikeFilter = Depends(), db: Session = Depends(get_db)):
    """
    Fetches a brand from the database based on the provided name.

    Parameters:
        name_param (BrandLookalikeFilter): The name of the searched brand.
        db (Session, optional): The database session.
        Defaults to the result of calling `get_db`.

    Returns:
        Optional[BrandOut]: The brand object fetched from the database.

    Raises:
        HTTPException: If no brand is found with the provided name,
            an HTTP 404 Not Found exception is raised.
        HTTPException: If the user does not have enough
            permissions to access to this endpoint.
    """
    brand = brand_crud.get_one_lookalike(db, name_param)
    if not brand:
        name = name_param.model_dump()['name']
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Brand with name {name} not found"
        )
    return brand


@router.get(
    "/{id}",
    response_model=Optional[BrandOut],
    status_code=status.HTTP_200_OK,
)
def fetch_brand_by_id(
    id: int, db: Session = Depends(get_db)
) -> BrandOut:
    """
    Fetches a brand by its ID.

    Parameters:
        id (int): The ID of the brand.
        db (Session): The database session.

    Returns:
        BrandOut: The fetched brand with its full parent chain.

    Notes:
        - Returns the complete parent chain (parent, parent's parent, etc.)
        - Child brands will inherit scores from root parent brand if they don't have their own

    Raises:
        HTTPException: If the brand is not found.
    """
    brand = brand_crud.get_one(db, Brand.id == id)
    if brand is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Brand with id {id} not found",
        )

    return brand


@router.post(
    "/",
    response_model=BrandOut,
    status_code=status.HTTP_201_CREATED,
    response_model_exclude_none=True,
    response_model_exclude_unset=True,
)
def create_brand(
    brand_create: Annotated[
        BrandCreate,
        Body(
            examples=[
                {
                    "name": "Brand name",
                    "parent_id": 1,
                }
            ]
        ),
    ],
    db: Session = Depends(get_db),
):
    """
    Create a brand.

    Parameters:
        brand_create (BrandCreate): The brand data to be created.
        db (Session, optional): The database session.
            Defaults to Depends(get_db).


    Returns:
        BrandOut: The created brand.

    Raises:
        HTTPException: If a brand with same ean provided exists.
        HTTPException: If a parent brand provided does not exists.
        HTTPException: If there is an error creating
            the brand in the database.
    """
    existing = brand_crud.get_one(db, Brand.name.ilike(brand_create.name.strip()))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Brand with name {existing.name} already exists",
        )

    try:
        brand = brand_crud.create(
            db, brand_create
        )
    except IntegrityError as e:
        error_message = str(e.orig)
        if "unique constraint" in error_message.lower() and "name" in error_message.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Brand with name {brand_create.name} already exists",
            ) from e
        elif "foreign key constraint" in error_message.lower() and "parent_id" in error_message.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Brand with id {brand_create.parent_id} does not exist",
            ) from e
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Data integrity error: {error_message}",
            ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Couldn't create brand. Error: {str(e)}",
        ) from e
    return brand


@router.put(
    "/{id}",
    response_model=BrandOut,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(RoleChecker(["contributor", "admin"]))]
)
def update_brand(
    id: int,
    brand_update: BrandUpdate,
    db: Session = Depends(get_db)
):
    """
    Update a brand by its ID.

    Parameters:
        id (int): The ID of the brand to be updated.
        brand_update (BrandUpdate): The updated brand data.
        db (Session, optional): The database session.
            Defaults to Depends(get_db).

    Returns:
        BrandOut: The updated brand.

    Raises:
        HTTPException: If the brand does not exist or
            the user does not have enough permissions.
        HTTPException: If there is an error updating
            the brand in the database.
    """
    brand = brand_crud.get_one(db, Brand.id == id)
    if brand is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Brand with id {id} not found",
        )

    try:
        brand = brand_crud.update(db, brand, brand_update)
    except IntegrityError as e:
        error_message = str(e.orig)
        if "unique constraint" in error_message.lower() and "name" in error_message.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Brand with name {brand_update.name} already exists",
            ) from e
        elif "foreign key constraint" in error_message.lower() and "parent_id" in error_message.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Brand with id {brand_update.parent_id} does not exist",
            ) from e
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Data integrity error: {error_message}",
            ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Couldn't update brand with id {id}. Error: {str(e)}",
        ) from e
    return brand


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(RoleChecker(["contributor", "admin"]))])
def delete_brand(
    id: int,
    db: Session = Depends(get_db),
):
    """
    Deletes a brand by its ID.

    Parameters:
        id (int): The ID of the brand to delete.
        db (Session): The database session.

    Returns:
        dict: A dictionary containing the detail that
            the brand with the given ID was deleted.

    Raises:
        HTTPException: If the brand with the given ID is not found.
        HTTPException: If the user does not have enough
            permissions to delete the brand.
        HTTPException: If there is an error while
            deleting the brand from the database.
    """
    brand = brand_crud.get_one(db, Brand.id == id)
    if brand is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Brand with id {id} not found. Cannot delete.",
        )
    try:
        logo_path = brand.logo_path
        brand_crud.delete(db, brand)
        # Delete the physical file if it exists
        if logo_path:
            file_service.delete_image(logo_path)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Couldn't delete brand with id {id}. Error: {str(e)}",
        ) from e


@router.post("/{brand_id}/upload-logo", response_model=BrandOut, status_code=status.HTTP_200_OK)
def upload_brand_logo(
    *,
    db: Session = Depends(get_db),
    brand_id: int,
    file: UploadFile = File(...,
                            description="Image du logo (JPG, PNG, WebP max 5MB)")
):
    """
    Upload a logo for a brand.

    - **brand_id**: ID of the brand
    - **file**: Image file (JPG, PNG, WebP, max 5MB)

    The file will be saved in `/uploads/brands/` and the path will be updated in the database.
    """
    # Check if the brand exists
    brand = brand_crud.get_one(db, Brand.id == brand_id)
    if not brand:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Brand with id {brand_id} not found"
        )

    try:
        # Save the file and get the path
        logo_path = file_service.save_image(
            brand, file_service.brands_dir, file)
        # Update the brand with the new logo path
        brand_update = BrandUpdate(logo_path=logo_path)
        updated_brand = brand_crud.update(db, brand, brand_update)

        return updated_brand

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error uploading logo: {str(e)}"
        ) from e


@router.delete("/{brand_id}/logo", status_code=status.HTTP_204_NO_CONTENT)
def delete_brand_logo(
    *,
    db: Session = Depends(get_db),
    brand_id: int
):
    """
    Delete the logo of a brand.

    - **brand_id**: ID of the brand
    """

    # Check if the brand exists
    brand = brand_crud.get_one(db, Brand.id == brand_id)
    if not brand:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Brand with id {brand_id} not found"
        )

    try:
        # Delete the physical file if it exists
        if brand.logo_path:
            file_service.delete_image(brand.logo_path)

        # Update the brand to remove the logo path
        brand_update = BrandUpdate(logo_path=None)
        brand_crud.update(db, brand, brand_update)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting logo: {str(e)}"
        ) from e
