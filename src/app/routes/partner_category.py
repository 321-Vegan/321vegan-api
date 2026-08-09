from typing import Annotated, List, Optional, Tuple

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.routes.dependencies import get_admin_or_client, get_pagination_params, get_sort_by_params, RoleChecker
from app.crud.partner_category import partner_category_crud
from app.database.db import get_db
from app.log import get_logger
from app.models.partner_category import PartnerCategory
from app.schemas.partner_category import PartnerCategoryCreate, PartnerCategoryOut, PartnerCategoryUpdate, PartnerCategoryOutPaginated, PartnerCategoryFilters

log = get_logger(__name__)

router = APIRouter(dependencies=[Depends(get_admin_or_client)])


@router.get(
    "/", response_model=List[Optional[PartnerCategoryOut]], status_code=status.HTTP_200_OK
)
def fetch_all_partner_categories(db: Session = Depends(get_db)) -> List[Optional[PartnerCategoryOut]]:
    """
    Fetch all partner categories.

    This function fetches all partner categories from the database.

    Parameters:
        db (Session): The database session.

    Returns:
        List[PartnerCategoryOut]: The list of partner categories fetched from the database.
    """
    return db.query(PartnerCategory).order_by(PartnerCategory.display_order).all()


@router.get(
    "/search", response_model=Optional[PartnerCategoryOutPaginated], status_code=status.HTTP_200_OK
)
def fetch_paginated_partner_categories(
    db: Session = Depends(get_db),
    pagination_params: Tuple[int, int] = Depends(get_pagination_params),
    orderby_params: Tuple[str, bool] = Depends(get_sort_by_params),
    filter_params: PartnerCategoryFilters = Depends()
) -> Optional[PartnerCategoryOutPaginated]:
    """
    Fetch many partner categories.

    This function fetches all partner categories from the database
    based on the pagination parameters.

    Parameters:
        db (Session): The database session.
        pagination_params (Tuple[int, int]): The pagination parameters (skip, limit).
        orderby_params (Tuple[str, bool]): The order by parameters (sortby, descending).
        filter_params (PartnerCategoryFilters): The filter parameters.

    Returns:
        PartnerCategoryOutPaginated: The list of partner categories fetched from the database with pagination data.
    """
    page, size = pagination_params
    sortby, descending = orderby_params
    categories, total = partner_category_crud.get_many(
        db,
        skip=page,
        limit=size,
        order_by=sortby,
        descending=descending,
        **filter_params.model_dump(exclude_none=True)
    )
    pages = (total + size - 1) // size
    return {
        "items": categories,
        "total": total,
        "page": page,
        "size": size,
        "pages": pages
    }


@router.get(
    "/{id}",
    response_model=Optional[PartnerCategoryOut],
    status_code=status.HTTP_200_OK,
)
def fetch_partner_category_by_id(
    id: int, db: Session = Depends(get_db)
) -> PartnerCategoryOut:
    """
    Fetches a partner category by its ID.

    Parameters:
        id (int): The ID of the partner category.
        db (Session): The database session.

    Returns:
        PartnerCategoryOut: The fetched partner category.

    Raises:
        HTTPException: If the partner category is not found.
    """
    category = partner_category_crud.get_one(db, PartnerCategory.id == id)
    if category is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Partner category with id {id} not found",
        )
    return category


@router.post(
    "/",
    response_model=PartnerCategoryOut,
    status_code=status.HTTP_201_CREATED,
    response_model_exclude_none=True,
    response_model_exclude_unset=True,
    dependencies=[Depends(RoleChecker(["admin"]))],
)
def create_partner_category(
    category_create: Annotated[
        PartnerCategoryCreate,
        Body(
            examples=[
                {
                    "name": "Online Stores",
                }
            ]
        ),
    ],
    db: Session = Depends(get_db),
):
    """
    Create a partner category.

    Parameters:
        category_create (PartnerCategoryCreate): The partner category data to be created.
        db (Session, optional): The database session.
            Defaults to Depends(get_db).

    Returns:
        PartnerCategoryOut: The created partner category.

    Raises:
        HTTPException: If a partner category with same name provided exists.
        HTTPException: If there is an error creating the partner category in the database.
    """
    try:
        category = partner_category_crud.create(db, category_create)
    except IntegrityError as e:
        error_message = str(e.orig)
        if "unique constraint" in error_message.lower() and "name" in error_message.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Partner category with name {category_create.name} already exists",
            ) from e
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Data integrity error: {error_message}",
            ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Couldn't create partner category. Error: {str(e)}",
        ) from e
    return category


@router.put(
    "/{id}",
    response_model=PartnerCategoryOut,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(RoleChecker(["admin"]))],
)
def update_partner_category(
    id: int,
    category_update: PartnerCategoryUpdate,
    db: Session = Depends(get_db)
):
    """
    Update a partner category by its ID.

    Parameters:
        id (int): The ID of the partner category to be updated.
        category_update (PartnerCategoryUpdate): The updated partner category data.
        db (Session, optional): The database session.
            Defaults to Depends(get_db).

    Returns:
        PartnerCategoryOut: The updated partner category.

    Raises:
        HTTPException: If the partner category does not exist or
            the user does not have enough permissions.
        HTTPException: If there is an error updating
            the partner category in the database.
    """
    category = partner_category_crud.get_one(db, PartnerCategory.id == id)
    if category is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Partner category with id {id} not found",
        )

    try:
        category = partner_category_crud.update(db, category, category_update)
    except IntegrityError as e:
        error_message = str(e.orig)
        if "unique constraint" in error_message.lower() and "name" in error_message.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Partner category with name {category_update.name} already exists",
            ) from e
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Data integrity error: {error_message}",
            ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Couldn't update partner category with id {id}. Error: {str(e)}",
        ) from e
    return category


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(RoleChecker(["admin"]))])
def delete_partner_category(
    id: int,
    db: Session = Depends(get_db),
):
    """
    Deletes a partner category by its ID.

    Parameters:
        id (int): The ID of the partner category to delete.
        db (Session): The database session.

    Returns:
        None

    Raises:
        HTTPException: If the partner category with the given ID is not found.
        HTTPException: If the user does not have enough
            permissions to delete the partner category.
        HTTPException: If there is an error while
            deleting the partner category from the database.
    """
    category = partner_category_crud.get_one(db, PartnerCategory.id == id)
    if category is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Partner category with id {id} not found. Cannot delete.",
        )
    try:
        partner_category_crud.delete(db, category)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Couldn't delete partner category with id {id}. Error: {str(e)}",
        ) from e
