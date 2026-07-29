from typing import Annotated, List, Optional, Tuple

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.routes.dependencies import get_current_superuser, get_pagination_params, get_sort_by_params, RoleChecker, get_current_active_user_or_client, get_admin_or_client, get_current_active_user
from app.crud import user_crud
from app.database.db import get_db
from app.log import get_logger
from app.models import ApiClient, User
from app.models.product import Product
from app.models.user import UserRole
from app.models.error_report import ErrorReport
from app.models.scan_event import ScanEvent
from app.schemas.user import UserCreate, UserOutPaginated, UserOut, UserUpdate, UserFilters, UserUpdateOwn, UserPatch, ScanCountIncrement, ScanCountInit, ScanCountOut
from typing import Literal
from app.security import get_password_hash
from app.services.xp_service import award_xp, XPAction

log = get_logger(__name__)


router = APIRouter()


@router.get(
    "/", response_model=List[Optional[UserOut]], status_code=status.HTTP_200_OK, dependencies=[Depends(RoleChecker(["admin"]))]
)
def fetch_all_users(
    db: Session = Depends(get_db),
):
    """
    Fetches all users.

    Parameters:
        db (Session): The database session.

    Returns:
        List[Optional[UserOut]]: A list of user objects,
            or None if there are no users.

    Raises:
        HTTPException: If the user does not have enough
            permissions to access to this endpoint.
    """

    return user_crud.get_all(db)


@router.get(
    "/search", response_model=Optional[UserOutPaginated], status_code=status.HTTP_200_OK, dependencies=[Depends(RoleChecker(["admin"]))]
)
def fetch_paginated_users(
    db: Session = Depends(get_db), pagination_params: Tuple[int, int] = Depends(get_pagination_params),
    orderby_params: Tuple[str, bool] = Depends(get_sort_by_params),
    filter_params: UserFilters = Depends()
) -> Optional[UserOutPaginated]:
    """
    Fetches all users with pagination.

    Parameters:
        db (Session): The database session.
        pagination_params (Tuple[int, int]): The pagination parameters (skip, limit).
        orderby_params (Tuple[str, bool]): The order by parameters (sortby, descending).

    Returns:
        Optional[UserOutPaginated]: A list of user objects,
            or None if there are no users.

    Raises:
        HTTPException: If the user does not have enough
            permissions to access to this endpoint.
    """

    page, size = pagination_params
    sortby, descending = orderby_params
    users, total = user_crud.get_many(
        db,
        skip=page,
        limit=size,
        order_by=sortby,
        descending=descending,
        **filter_params.model_dump(exclude_none=True)
    )
    pages = (total + size - 1) // size
    return {
        "items": users,
        "total": total,
        "page": page,
        "size": size,
        "pages": pages
    }


@router.get(
    "/leaderboard", response_model=List[Optional[UserOut]], status_code=status.HTTP_200_OK,
    dependencies=[Depends(RoleChecker(["contributor", "admin"]))]
)
def fetch_leaderboard(
    sortby: Literal["nb_products_modified", "nb_checkings"] = "nb_products_modified",
    limit: int = 20,
    db: Session = Depends(get_db),
):
    return user_crud.get_leaderboard(db, sortby=sortby, limit=limit)


@router.post("/me/scans", response_model=ScanCountOut, status_code=status.HTTP_200_OK)
def increment_my_scan_count(
    payload: ScanCountIncrement = Body(default=ScanCountIncrement()),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ScanCountOut:
    """
    Increment the current user's scan counter.

    Called by the app on each product scan. `count` defaults to 1 and can
    be greater to sync several scans made offline in a single request.

    Parameters:
        payload (ScanCountIncrement): The number of scans to add.
        db (Session): The database session.
        current_user (User): The currently authenticated user.

    Returns:
        ScanCountOut: The new total scan count for the user.
    """
    new_count = user_crud.increment_scan_count(
        db, current_user.id, payload.count)
    if new_count is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    xp_awarded = award_xp(
        db, current_user, XPAction.BASIC_SCAN,
        reference_type="scan_count_increment", quantity=payload.count,
    )
    return {"scan_count": new_count, "xp_awarded": xp_awarded, "level": current_user.level}


@router.put("/me/scans", response_model=ScanCountOut, status_code=status.HTTP_200_OK)
def initialize_my_scan_count(
    payload: ScanCountInit,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ScanCountOut:
    """
    Seed the current user's scan counter from the app's local count.

    Called once after account creation/login so users who scanned before
    having an account don't restart at zero. Only applies if the server
    counter is still 0; otherwise the existing count is returned unchanged.

    Parameters:
        payload (ScanCountInit): The initial scan count.
        db (Session): The database session.
        current_user (User): The currently authenticated user.

    Returns:
        ScanCountOut: The current total scan count for the user.
    """
    scan_count = user_crud.initialize_scan_count(
        db, current_user.id, payload.count)
    if scan_count is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    return {"scan_count": scan_count}


@router.get("/{id}", response_model=UserOut, status_code=status.HTTP_200_OK, dependencies=[Depends(RoleChecker(["admin"]))])
def fetch_user_by_id(id: int, db: Session = Depends(get_db)):
    """
    Fetches a user by their ID from the database.

    Parameters:
        id (int): The ID of the user to fetch.
        db (Session): The database session.

    Returns:
        UserOut: The user object fetched from the database.

    Raises:
        HTTPException: If the user does not have enough
            permissions to access to this endpoint.
        HTTPException: If the user with the specified ID is not found in the database.
    """
    user = user_crud.get_one(db, User.id == id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with {id} not found",
        )
    return user


@router.get("/email/{email}", response_model=UserOut, status_code=status.HTTP_200_OK, dependencies=[Depends(RoleChecker(["admin"]))])
def fetch_user_by_email(email: str, db: Session = Depends(get_db)):
    """
    Fetches a user from the database based on the provided email.

    Parameters:
        email (str): The email address of the user.
        db (Session, optional): The database session.
        Defaults to the result of calling `get_db`.

    Returns:
        UserOut: The user object fetched from the database.

    Raises:
        HTTPException: If no user is found with the provided email,
            an HTTP 404 Not Found exception is raised.
        HTTPException: If the user does not have enough
            permissions to access to this endpoint.
    """
    user = user_crud.get_user_by_email(db, email=email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"User with {email} not found"
        )
    return user


@router.post("/", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    user_create: Annotated[
        UserCreate,
        Body(
            examples=[
                {
                    "role": "user",
                    "nickname": "User name",
                    "email": "example@example.com",
                    "password": "12345678",
                    "is_active": True,
                    "vegan_since": "2023-01-01T00:00:00Z",
                    "nb_products_sent": 0
                }
            ]
        ),
    ],
    db: Session = Depends(get_db),
    current_admin_or_client: User | ApiClient = Depends(get_admin_or_client),
):
    """
    Create a new user.

    API clients (app registration) can only create regular users: the
    role is forced to "user". Only admins can create users with another
    role.

    Parameters:
        user_create (UserCreate): The user data to be created.
        db (Session): The database session.
        current_admin_or_client (User | ApiClient): The current admin user or API client.

    Returns:
        User: The newly created user.

    Raises:
        HTTPException: If a user with the same email already exists in the system.
        HTTPException: If the user is not an admin or the request is not authenticated with a valid API key.
    """
    if isinstance(current_admin_or_client, ApiClient):
        user_create.role = UserRole.USER.value
    user = user_crud.get_user_by_email(db, email=user_create.email)
    if user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"The user with this {user_create.email} already exists \
            in the system",
        )
    try:
        dict_user_create = user_create.model_dump()
        dict_user_create['password'] = get_password_hash(user_create.password)
        user_in = UserCreate(
            **dict_user_create,
        )
        user = user_crud.create(db, user_in)

    except IntegrityError as e:
        error_message = str(e.orig)
        if "unique constraint" in error_message.lower():
            if "email" in error_message.lower():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"User with EMAIL {user_create.email} already exists",
                ) from e
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Data integrity error: {error_message}",
            ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Couldn't create user. Error: {str(e)}",
        ) from e
    return user


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Delete a user by user ID.

    - Admins can delete any user except themselves.
    - Regular users can only delete their own account.

    Parameters:
        id (int): The ID of the user to delete.
        db (Session, optional): The database session. Defaults to Depends(get_db).
        current_user (User, optional): The current authenticated user.

    Raises:
        HTTPException: If the user is not found or the user tries to delete themselves (admin).
        HTTPException: If a non-admin tries to delete another user.
        HTTPException: If there is an error deleting the user.
    Returns:
        None
    """
    user = user_crud.get_one(db, User.id == id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with id {id} not found. Cannot delete.",
        )

    # If admin, cannot delete themselves
    if "admin" in getattr(current_user, "role", []):
        if user.id == current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admins cannot delete themselves",
            )
    # If not admin, can only delete themselves
    else:
        if user.id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only delete your own account",
            )
    try:
        db.query(Product).filter(Product.last_modified_by ==
                                 id).update({Product.last_modified_by: None})
        db.query(ErrorReport).filter(ErrorReport.created_by ==
                                     id).update({ErrorReport.created_by: None})
        db.query(ScanEvent).filter(ScanEvent.user_id ==
                                   id).update({ScanEvent.user_id: None})
        user_crud.delete(db, user)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Couldn't delete user with id {id}. Error: {str(e)}",
        ) from e


@router.put("/{id}", response_model=UserOut, status_code=status.HTTP_200_OK, dependencies=[Depends(RoleChecker(["admin"]))])
def update_user(
    id: int,
    user_update: UserUpdate,
    db: Session = Depends(get_db),
):
    """
    Update a user with the given ID.

    Parameters:
        id (int): The ID of the user to update.
        user_update (UserUpdate): The updated user information.
        db (Session, optional): The database session. Defaults to Depends(get_db).

    Returns:
        UserOut: The updated user information.

    Raises:
        HTTPException: If the user is not found.
        HTTPException: If there is an error updating the user.
        HTTPException: If the user does not have enough
            permissions to access to this endpoint.
    """
    user = user_crud.get_one(db, User.id == id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with id {id} not found. Cannot update.",
        )
    try:
        user = user_crud.update(db, user, user_update)
    except IntegrityError as e:
        error_message = str(e.orig)
        if "unique constraint" in error_message.lower():
            if "email" in error_message.lower():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"User with EMAIL {user_update.email} already exists",
                ) from e
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Data integrity error: {error_message}",
            ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Couldn't update user with id {id}. Error: {str(e)}",
        ) from e
    return user


CLIENT_PATCHABLE_USER_FIELDS = {"nickname", "vegan_since"}


@router.patch("/{id}", response_model=UserOut, status_code=status.HTTP_200_OK)
def patch_user(
    id: int,
    user_patch: UserPatch,
    db: Session = Depends(get_db),
    current_admin_or_client: User | ApiClient = Depends(get_admin_or_client),
):
    """
    Partially update a user with the given ID.
    Only the provided fields will be updated, other fields remain unchanged.

    API clients can only update the profile fields listed in
    CLIENT_PATCHABLE_USER_FIELDS. Only admins can update any other field.

    Parameters:
        id (int): The ID of the user to update.
        user_patch (UserPatch): The fields to update (only provided fields will be updated).
        db (Session, optional): The database session. Defaults to Depends(get_db).
        current_admin_or_client (User | ApiClient): The current admin user or API client.

    Returns:
        UserOut: The updated user information.

    Raises:
        HTTPException: If the user is not found.
        HTTPException: If there is an error updating the user.
        HTTPException: If the user does not have enough
            permissions to access to this endpoint.
        HTTPException: 403 if an API client tries to update a restricted field.
    """
    if isinstance(current_admin_or_client, ApiClient):
        forbidden = set(user_patch.model_dump(exclude_unset=True)) - \
            CLIENT_PATCHABLE_USER_FIELDS
        if forbidden:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"API clients cannot update: {', '.join(sorted(forbidden))}",
            )

    user = user_crud.get_one(db, User.id == id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with id {id} not found. Cannot update.",
        )

    # Hash password if it's being updated
    update_data = user_patch.model_dump(exclude_unset=True)
    if "password" in update_data:
        update_data["password"] = get_password_hash(update_data["password"])
        # Create a new UserPatch with the hashed password
        user_patch = UserPatch(**update_data)

    try:
        user = user_crud.update(db, user, user_patch)
    except IntegrityError as e:
        error_message = str(e.orig)
        if "unique constraint" in error_message.lower():
            if "email" in error_message.lower():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"User with EMAIL {update_data.get('email', '')} already exists",
                ) from e
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Data integrity error: {error_message}",
            ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Couldn't update user with id {id}. Error: {str(e)}",
        ) from e
    return user
