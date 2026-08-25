from typing import Annotated, List, Optional, Tuple

from fastapi import APIRouter, Body, Depends, HTTPException, status, File, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.routes.dependencies import get_admin_or_client, get_pagination_params, get_sort_by_params, RoleChecker
from app.crud.partner import partner_crud
from app.database.db import get_db
from app.log import get_logger
from app.models.partner import Partner
from app.schemas.partner import PartnerCreate, PartnerOut, PartnerUpdate, PartnerOutPaginated, PartnerFilters
from app.services.cache_service import TTLCache
from app.services.file_service import file_service

log = get_logger(__name__)

router = APIRouter(dependencies=[Depends(get_admin_or_client)])

# Partners change rarely; cache read-heavy list/search results to absorb traffic spikes.
_partners_cache = TTLCache(ttl_seconds=3600)


@router.get(
    "/", response_model=List[Optional[PartnerOut]], status_code=status.HTTP_200_OK
)
def fetch_all_partners(db: Session = Depends(get_db)) -> List[Optional[PartnerOut]]:
    """
    Fetch all partners.

    This function fetches all partners from the database.

    Parameters:
        db (Session): The database session.

    Returns:
        List[PartnerOut]: The list of partners fetched from the database.
    """
    def compute():
        partners = db.query(Partner).order_by(Partner.display_order).all()
        return [PartnerOut.model_validate(p, from_attributes=True) for p in partners]

    return _partners_cache.get_or_set("all", compute)


@router.get(
    "/search", response_model=Optional[PartnerOutPaginated], status_code=status.HTTP_200_OK
)
def fetch_paginated_partners(
    db: Session = Depends(get_db),
    pagination_params: Tuple[int, int] = Depends(get_pagination_params),
    orderby_params: Tuple[str, bool] = Depends(get_sort_by_params),
    filter_params: PartnerFilters = Depends()
) -> Optional[PartnerOutPaginated]:
    """
    Fetch many partners.

    This function fetches all partners from the database
    based on the pagination parameters.

    Parameters:
        db (Session): The database session.
        pagination_params (Tuple[int, int]): The pagination parameters (skip, limit).
        orderby_params (Tuple[str, bool]): The order by parameters (sortby, descending).
        filter_params (PartnerFilters): The filter parameters.

    Returns:
        PartnerOutPaginated: The list of partners fetched from the database with pagination data.
    """
    page, size = pagination_params
    sortby, descending = orderby_params
    filters = filter_params.model_dump(exclude_none=True)
    cache_key = (page, size, sortby, descending, tuple(sorted(filters.items())))

    def compute():
        partners, total = partner_crud.get_many(
            db,
            skip=page,
            limit=size,
            order_by=sortby,
            descending=descending,
            **filters
        )
        pages = (total + size - 1) // size
        return PartnerOutPaginated(
            items=[PartnerOut.model_validate(p, from_attributes=True) for p in partners],
            total=total,
            page=page,
            size=size,
            pages=pages
        )

    return _partners_cache.get_or_set(cache_key, compute)


@router.get(
    "/{id}",
    response_model=Optional[PartnerOut],
    status_code=status.HTTP_200_OK,
)
def fetch_partner_by_id(
    id: int, db: Session = Depends(get_db)
) -> PartnerOut:
    """
    Fetches a partner by its ID.

    Parameters:
        id (int): The ID of the partner.
        db (Session): The database session.

    Returns:
        PartnerOut: The fetched partner.

    Raises:
        HTTPException: If the partner is not found.
    """
    partner = partner_crud.get_one(db, Partner.id == id)
    if partner is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Partner with id {id} not found",
        )
    return partner


@router.post(
    "/",
    response_model=PartnerOut,
    status_code=status.HTTP_201_CREATED,
    response_model_exclude_none=True,
    response_model_exclude_unset=True,
    dependencies=[Depends(RoleChecker(["admin"]))],
)
def create_partner(
    partner_create: Annotated[
        PartnerCreate,
        Body(
            examples=[
                {
                    "name": "Partner name",
                    "url": "https://partner.com",
                    "description": "Partner description",
                    "discount_text": "10% off with code VEGAN10",
                    "discount_code": "VEGAN10",
                    "is_affiliate": True,
                    "show_code_in_website": True,
                    "category_id": 1
                }
            ]
        ),
    ],
    db: Session = Depends(get_db),
):
    """
    Create a partner.

    Parameters:
        partner_create (PartnerCreate): The partner data to be created.
        db (Session, optional): The database session.
            Defaults to Depends(get_db).

    Returns:
        PartnerOut: The created partner.

    Raises:
        HTTPException: If a partner with same name provided exists.
        HTTPException: If there is an error creating the partner in the database.
    """
    try:
        partner = partner_crud.create(db, partner_create)
    except IntegrityError as e:
        error_message = str(e.orig)
        if "unique constraint" in error_message.lower() and "name" in error_message.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Partner with name {partner_create.name} already exists",
            ) from e
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Data integrity error: {error_message}",
            ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Couldn't create partner. Error: {str(e)}",
        ) from e
    _partners_cache.clear()
    return partner


@router.put(
    "/{id}",
    response_model=PartnerOut,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(RoleChecker(["admin"]))],
)
def update_partner(
    id: int,
    partner_update: PartnerUpdate,
    db: Session = Depends(get_db)
):
    """
    Update a partner by its ID.

    Parameters:
        id (int): The ID of the partner to be updated.
        partner_update (PartnerUpdate): The updated partner data.
        db (Session, optional): The database session.
            Defaults to Depends(get_db).

    Returns:
        PartnerOut: The updated partner.

    Raises:
        HTTPException: If the partner does not exist or
            the user does not have enough permissions.
        HTTPException: If there is an error updating
            the partner in the database.
    """
    partner = partner_crud.get_one(db, Partner.id == id)
    if partner is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Partner with id {id} not found",
        )

    try:
        partner = partner_crud.update(db, partner, partner_update)
    except IntegrityError as e:
        error_message = str(e.orig)
        if "unique constraint" in error_message.lower() and "name" in error_message.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Partner with name {partner_update.name} already exists",
            ) from e
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Data integrity error: {error_message}",
            ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Couldn't update partner with id {id}. Error: {str(e)}",
        ) from e
    _partners_cache.clear()
    return partner


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(RoleChecker(["admin"]))])
def delete_partner(
    id: int,
    db: Session = Depends(get_db),
):
    """
    Deletes a partner by its ID.

    Parameters:
        id (int): The ID of the partner to delete.
        db (Session): The database session.

    Returns:
        None

    Raises:
        HTTPException: If the partner with the given ID is not found.
        HTTPException: If the user does not have enough
            permissions to delete the partner.
        HTTPException: If there is an error while
            deleting the partner from the database.
    """
    partner = partner_crud.get_one(db, Partner.id == id)
    if partner is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Partner with id {id} not found. Cannot delete.",
        )
    try:
        logo_path = partner.logo_path
        partner_crud.delete(db, partner)
        # Delete the physical logo file if it exists
        if logo_path:
            file_service.delete_image(logo_path)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Couldn't delete partner with id {id}. Error: {str(e)}",
        ) from e
    _partners_cache.clear()


@router.post("/{partner_id}/upload-logo", response_model=PartnerOut, status_code=status.HTTP_200_OK, dependencies=[Depends(RoleChecker(["admin"]))])
def upload_partner_logo(
    *,
    db: Session = Depends(get_db),
    partner_id: int,
    file: UploadFile = File(...,
                            description="Image du logo (JPG, PNG, WebP max 5MB)")
):
    """
    Upload a logo for a partner.

    - **partner_id**: ID of the partner
    - **file**: Image file (JPG, PNG, WebP, max 5MB)

    The file will be saved in `/uploads/partners/` and the path will be updated in the database.
    """

    # Check if the partner exists
    partner = partner_crud.get_one(db, Partner.id == partner_id)
    if not partner:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Partner with id {partner_id} not found"
        )

    try:
        # Save the file and get the path
        logo_path = file_service.save_image(
            partner, file_service.partners_dir, file)

        # Update the partner with the new logo path
        partner_update = PartnerUpdate(logo_path=logo_path)
        updated_partner = partner_crud.update(db, partner, partner_update)

        _partners_cache.clear()
        return updated_partner

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error uploading logo: {str(e)}"
        ) from e


@router.delete("/{partner_id}/logo", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(RoleChecker(["admin"]))])
def delete_partner_logo(
    *,
    db: Session = Depends(get_db),
    partner_id: int
):
    """
    Delete the logo of a partner.

    - **partner_id**: ID of the partner
    """

    # Check if the partner exists
    partner = partner_crud.get_one(db, Partner.id == partner_id)
    if not partner:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Partner with id {partner_id} not found"
        )

    try:
        # Delete the physical file if it exists
        if partner.logo_path:
            file_service.delete_image(partner.logo_path)

        # Update the partner to remove the logo path
        partner_update = PartnerUpdate(logo_path=None)
        partner_crud.update(db, partner, partner_update)
        _partners_cache.clear()

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting logo: {str(e)}"
        ) from e
