import time
from pathlib import Path
from typing import Annotated, List, Optional, Tuple
from fastapi import APIRouter, Body, Depends, HTTPException, status, File, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.routes.dependencies import get_current_active_user, get_pagination_params, get_sort_by_params, RoleChecker, get_current_active_user_or_client
from app.crud import product_crud
from app.crud.user import user_crud
from app.database.db import get_db
from app.log import get_logger
from app.models import Product, User
from app.models.product import ProductState
from app.schemas.product import ProductCreate, ProductOut, ProductUpdate, ProductOutPaginated, ProductOutCount, ProductFilters, ProductFile
from app.services.s3_file_manager import s3_file_manager

log = get_logger(__name__)

router = APIRouter()


@router.get(
    "/", response_model=List[Optional[ProductOut]], status_code=status.HTTP_200_OK, dependencies=[Depends(get_current_active_user)]
)
def fetch_all_products(db: Session = Depends(get_db)) -> List[Optional[ProductOut]]:
    """
    Fetch all products.

    This function fetches all products from the
    database.

    Parameters:
        db (Session): The database session.

    Returns:
        List[Optional[ProductOut]]: The list of products fetched from the database.
    """
    return product_crud.get_all(db)


@router.get(
    "/count", response_model=Optional[ProductOutCount], status_code=status.HTTP_200_OK, dependencies=[Depends(get_current_active_user)]
)
def fetch_count_products(
    db: Session = Depends(get_db),
    filter_params: ProductFilters = Depends(),
) -> Optional[ProductOutCount]:
    """
    Fetch how many products.

    This function fetches total product count from the
    database based on the filters parameters.

    Parameters:
        db (Session): The database session.
        filter_params (ProductFilters): The filters parameters.

    Returns:
        Optional[ProductOutCount]: The total count of products fetched from the database with filter datas.
    """
    total = product_crud.count(
        db,
        **filter_params.model_dump(exclude_none=True)
    )
    return {
        "total": total
    }


@router.get(
    "/search", response_model=Optional[ProductOutPaginated], status_code=status.HTTP_200_OK, dependencies=[Depends(get_current_active_user)]
)
def fetch_paginated_products(
    db: Session = Depends(get_db),
    pagination_params: Tuple[int, int] = Depends(get_pagination_params),
    orderby_params: Tuple[str, bool] = Depends(get_sort_by_params),
    filter_params: ProductFilters = Depends(),
) -> Optional[ProductOutPaginated]:
    """
    Fetch many products.

    This function fetches all products from the
    database based on the pagination parameters.

    Parameters:
        db (Session): The database session.
        pagination_params (Tuple[int, int]): The pagination parameters (skip, limit).
        orderby_params (Tuple[str, bool]): The order by parameters (sortby, descending).

    Returns:
        Optional[ProductOutPaginated]: The list of products fetched from the database with pagination datas.
    """
    page, size = pagination_params
    sortby, descending = orderby_params
    products, total = product_crud.get_many(
        db,
        skip=page,
        limit=size,
        order_by=sortby,
        descending=descending,
        **filter_params.model_dump(exclude_none=True)
    )
    pages = (total + size - 1) // size
    return {
        "items": products,
        "total": total,
        "page": page,
        "size": size,
        "pages": pages
    }


@router.get(
    "/{id}",
    response_model=Optional[ProductOut],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(get_current_active_user)]
)
def fetch_product_by_id(
    id: int, db: Session = Depends(get_db)
) -> ProductOut:
    """
    Fetches a product by its ID.

    Parameters:
        id (int): The ID of the product.
        db (Session): The database session.

    Returns:
        ProductOut: The fetched product.

    Raises:
        HTTPException: If the product is not found.
    """
    product = product_crud.get_one(db, Product.id == id)
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with id {id} not found",
        )
    return product


@router.get("/ean/{ean}", response_model=ProductOut, status_code=status.HTTP_200_OK, dependencies=[Depends(get_current_active_user_or_client)])
def fetch_product_by_ean(ean: str, db: Session = Depends(get_db)):
    """
    Fetches a product from the database based on the provided ean.

    Parameters:
        ean (str): The ean of the product.
        db (Session, optional): The database session.
        Defaults to the result of calling `get_db`.

    Returns:
        ProductOut: The product object fetched from the database.

    Raises:
        HTTPException: If no product is found with the provided ean,
            an HTTP 404 Not Found exception is raised.
        HTTPException: If the user does not have enough
            permissions to access to this endpoint.
    """
    product = product_crud.get_product_by_ean(db, ean=ean)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Product with ean {ean} not found"
        )
    return product


@router.post(
    "/",
    response_model=ProductOut,
    status_code=status.HTTP_201_CREATED,
    response_model_exclude_none=True,
    response_model_exclude_unset=True,
    dependencies=[Depends(get_current_active_user_or_client)]
)
def create_product(
    product_create: Annotated[
        ProductCreate,
        Body(
            examples=[
                {
                    "ean": "1234567890",
                    "name": "Product name",
                    "description": "Long text description",
                    "problem_description": "Long text problem description",
                    "brand_id": 1,
                    "status": 'STATUS',
                    "biodynamic": False,
                    "state": 'STATE',
                    "has_non_vegan_old_receipe": True,
                }
            ]
        ),
    ],
    db: Session = Depends(get_db),
    current_user_or_client=Depends(get_current_active_user_or_client)
):
    """
    Create a product.

    Parameters:
        product_create (ProductCreate): The product data to be created.
        db (Session, optional): The database session.
            Defaults to Depends(get_db).

    Returns:
        ProductOut: The created product.

    Raises:
        HTTPException: If a product with same ean provided exists.
        HTTPException: If a brand provided does not exists.
        HTTPException: If there is an error creating
            the product in the database.
    """
    try:
        user = None
        if isinstance(current_user_or_client, User):
            user = current_user_or_client
        elif product_create.user_id is not None:
            user = user_crud.get_one(db, User.id == product_create.user_id)
        product = product_crud.create(db, product_create, user)

    except IntegrityError as e:
        error_message = str(e.orig)
        if "unique constraint" in error_message.lower() and "ean" in error_message.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Product with EAN {product_create.ean} already exists",
            ) from e
        elif "foreign key constraint" in error_message.lower() and "brand_id" in error_message.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Brand with id {product_create.brand_id} does not exist",
            ) from e
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Data integrity error: {error_message}",
            ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Couldn't create product. Error: {str(e)}",
        ) from e
    return product


@router.put(
    "/{id}",
    response_model=ProductOut,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(RoleChecker(["contributor", "admin"]))]
)
def update_product(
    id: int,
    product_update: ProductUpdate,
    db: Session = Depends(get_db),
    active_user: User = Depends(get_current_active_user),
):
    """
    Update a product by its ID.

    Parameters:
        id (int): The ID of the product to be updated.
        product_update (ProductUpdate): The updated product data.
        db (Session, optional): The database session.
            Defaults to Depends(get_db).

    Returns:
        ProductOut: The updated product.

    Raises:
        HTTPException: If the product does not exist or
            the user does not have enough permissions.
        HTTPException: If there is an error updating
            the product in the database.
    """
    product = product_crud.get_one(db, Product.id == id)
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with id {id} not found",
        )

    try:
        if active_user.is_contributor() and product.state == ProductState.PUBLISHED:
            # Only override the state; keep every other field the client
            # actually sent (avoids clobbering non-null columns with defaults).
            dict_product_update = product_update.model_dump(exclude_unset=True)
            dict_product_update['state'] = ProductState.WAITING_PUBLISH
            product_update = ProductUpdate(
                **dict_product_update,
            )
        product = product_crud.update(db, product, product_update, active_user)
    except IntegrityError as e:
        error_message = str(e.orig)
        if "unique constraint" in error_message.lower() and "ean" in error_message.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Product with EAN {product_update.ean} already exists",
            ) from e
        elif "foreign key constraint" in error_message.lower() and "brand_id" in error_message.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Brand with id {product_update.brand_id} does not exist",
            ) from e
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Data integrity error: {error_message}",
            ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Couldn't update product with id {id}. Error: {str(e)}",
        ) from e
    return product


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(RoleChecker(["contributor", "admin"]))])
def delete_product(
    id: int,
    db: Session = Depends(get_db)
):
    """
    Deletes a product by its ID.

    Parameters:
        id (int): The ID of the product to delete.
        db (Session): The database session.

    Returns:
        dict: A dictionary containing the detail that
            the product with the given ID was deleted.

    Raises:
        HTTPException: If the product with the given ID is not found.
        HTTPException: If the user does not have enough
            permissions to delete the product.
        HTTPException: If there is an error while
            deleting the product from the database.
    """
    product = product_crud.get_one(db, Product.id == id)
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with id {id} not found. Cannot delete.",
        )

    try:
        image_path = product.image
        product_crud.delete(db, product)
        # Delete the physical file if it exists
        if image_path:
            s3_file_manager.delete_file(image_path)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Couldn't delete product with id {id}. Error: {str(e)}",
        ) from e


@router.post("/{id}/image", response_model=ProductOut, status_code=status.HTTP_200_OK)
def upload_product_image(
    *,
    db: Session = Depends(get_db),
    id: int,
    file: UploadFile = File(...,
                            description="Image (JPG, PNG, WebP max 5MB)"),
    active_user: User = Depends(get_current_active_user),
):
    """
    Upload an image for a product.

    id (int): The ID of the product to be updated.
    file (UploadFile): Image file (JPG, PNG, WebP, max 5MB)

    The file will be saved in `/uploads/products/` and the path will be updated in the database.
    """
    # Check if the product exists
    product = product_crud.get_one(db, Product.id == id)
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with id {id} not found. Cannot upload file.",
        )

    try:
        old_image = product.image
        # Save the file and get the path
        file_extension = Path(file.filename or "").suffix.lower()
        filename = f"product_{product.id}_{product.ean}_{time.strftime('%Y%m%d_%H%M%S')}{file_extension}"
        s3_file_manager.upload_image(filename, file)

        # Update the product with the new image path
        product_update = ProductFile(image=filename)
        updated_product = product_crud.update(
            db, product, product_update, active_user, increment_modified=False)

        # Delete the physical old image if it exists
        if old_image:
            s3_file_manager.delete_file(old_image)

        return updated_product
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error uploading image: {str(e)}"
        ) from e


@router.delete("/{id}/image", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(RoleChecker(["contributor", "admin"]))])
def delete_product_image(
    *,
    db: Session = Depends(get_db),
    id: int,
    active_user: User = Depends(get_current_active_user),
):
    """
    Delete the image of a product.

    id (int): The ID of the product to be updated.
    """

    # Check if the product exists
    product = product_crud.get_one(db, Product.id == id)
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Product with id {id} not found"
        )

    try:
        # Delete the physical file if it exists
        if product.image:
            s3_file_manager.delete_file(product.image)

        # Update the product to remove the logo path
        product_update = ProductFile(image=None)
        product_crud.update(db, product, product_update, active_user, increment_modified=False)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting image: {str(e)}"
        ) from e
