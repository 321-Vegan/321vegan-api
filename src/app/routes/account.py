from typing import List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.routes.dependencies import get_current_active_user, get_pagination_params, get_sort_by_params
from app.crud import user_crud, b12_intake_crud
from app.crud.error_reports import error_report_crud
from app.database.db import get_db
from app.log import get_logger
from app.models import User
from app.schemas.b12_intake import B12IntakeOut
from app.schemas.error_report import ErrorReportOutPaginated
from app.schemas.user import UserOut, UserUpdateOwn
from app.schemas.auth import EmailChangeRequest, PasswordChangeRequest
from app.security import get_password_hash, verify_password, validate_password_strength
from app.services.email import email_service

log = get_logger(__name__)


router = APIRouter()


@router.get("/", response_model=UserOut, status_code=status.HTTP_200_OK)
def fetch_current_active_user(user: User = Depends(get_current_active_user)):
    """
    Fetches the current active user from the database.

    Parameters:
        user (User, optional): The current active user.

    Returns:
        UserOut: The user object fetched from the database.

    Raises:
        HTTPException: If the current active user is not found.
    """

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Current active user not found",
        )
    return user


@router.put("/", response_model=UserOut, status_code=status.HTTP_200_OK)
def update_current_active_user(
    user_update: UserUpdateOwn,
    db: Session = Depends(get_db),
    active_user: User = Depends(get_current_active_user),
):
    """
    Update a current active user.

    Parameters:
        user_update (UserUpdateOwn): The updated user information.
        db (Session, optional): The database session. Defaults to Depends(get_db).
        active_user (User, optional): The current active user.

    Returns:
        UserOut: The updated user information.

    Raises:
        HTTPException: If the user is not found.
        HTTPException: If there is an error updating the user.
    """

    if active_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Current active user not found. Cannot update.",
        )
    try:
        dict_user_update = user_update.model_dump(
            exclude_unset=True
        )  # exclude_unset=True -
        # do not update fields with None
        if 'password' in dict_user_update:
            dict_user_update['password'] = get_password_hash(
                user_update.password)
        user_in = UserUpdateOwn(
            **dict_user_update
        )
        user = user_crud.update(db, active_user, user_in)
    except IntegrityError as e:
        error_message = str(e.orig)
        if "unique constraint" in error_message.lower() and "nickname" in error_message.lower():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"User with NICKNAME {user_in.nickname} already exists",
            ) from e
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Data integrity error: {error_message}",
            ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Couldn't update current active user. Error: {str(e)}",
        ) from e
    return user

@router.get(
    "/error-reports",
    response_model=Optional[ErrorReportOutPaginated],
    status_code=status.HTTP_200_OK,
)
def fetch_my_error_reports(
    db: Session = Depends(get_db),
    pagination_params: Tuple[int, int] = Depends(get_pagination_params),
    orderby_params: Tuple[str, bool] = Depends(get_sort_by_params),
    active_user: User = Depends(get_current_active_user),
) -> Optional[ErrorReportOutPaginated]:
    """
    Fetch the error reports created by the current user.

    Parameters:
        db (Session): The database session.
        pagination_params (Tuple[int, int]): The pagination parameters (skip, limit).
        orderby_params (Tuple[str, bool]): The order by parameters (sortby, descending).
        active_user (User): The current active user.

    Returns:
        Optional[ErrorReportOutPaginated]: The current user's error reports with pagination datas.
    """
    page, size = pagination_params
    sortby, descending = orderby_params
    error_reports, total = error_report_crud.get_many(
        db,
        skip=page,
        limit=size,
        order_by=sortby,
        descending=descending,
        created_by=active_user.id,
    )
    pages = (total + size - 1) // size
    return {
        "items": error_reports,
        "total": total,
        "page": page,
        "size": size,
        "pages": pages
    }


@router.get(
    "/b12-intakes",
    response_model=List[B12IntakeOut],
    status_code=status.HTTP_200_OK,
)
def fetch_my_b12_intakes(
    db: Session = Depends(get_db),
    active_user: User = Depends(get_current_active_user),
) -> List[B12IntakeOut]:
    """
    Fetch the B12 intakes of the current user, most recent first.

    Parameters:
        db (Session): The database session.
        active_user (User): The current active user.

    Returns:
        List[B12IntakeOut]: The current user's B12 intakes.
    """
    return b12_intake_crud.get_by_user(db, active_user.id)


@router.patch("/password", status_code=status.HTTP_200_OK)
def change_password(
    request: PasswordChangeRequest,
    db: Session = Depends(get_db),
    active_user: User = Depends(get_current_active_user),
):
    """
    Change the current user's password.

    Parameters:
        request (PasswordChangeRequest): The current and new password.
        db (Session): The database session.
        active_user (User): The current active user.

    Returns:
        Dict[str, str]: A confirmation message.

    Raises:
        HTTPException: If the current password is incorrect.
        HTTPException: If the new password doesn't meet security requirements.
    """
    if not verify_password(request.current_password, active_user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect password.",
        )

    is_valid, error_messages = validate_password_strength(request.new_password)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"errors": error_messages},
        )

    user_crud.change_password(db, active_user, request.new_password)

    email_service.send_password_change_notification(
        email=active_user.email,
        user_nickname=active_user.nickname,
    )

    return {"detail": "Password has been updated successfully."}


@router.patch("/email", status_code=status.HTTP_200_OK)
def request_email_change(
    request: EmailChangeRequest,
    db: Session = Depends(get_db),
    active_user: User = Depends(get_current_active_user),
):
    """
    Request an email change for the current user.
 
    Parameters:
        request (EmailChangeRequest): The email change request containing new_email and current_password.
        db (Session): The database session.
        active_user (User): The current active user.
 
    Returns:
        Dict[str, str]: A confirmation message.
 
    Raises:
        HTTPException: If the user is not found.
        HTTPException: If the password is incorrect.
        HTTPException: If the new email is already in use.
        HTTPException: If the confirmation email fails to send.
    """
    if not active_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Current active user not found.",
        )
 
    if not verify_password(request.current_password, active_user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect password.",
        )
 
    token = user_crud.request_email_change(db, active_user, request.new_email)
 
    if not token:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already in use.",
        )
 
    email_sent = email_service.send_email_change_confirmation(
        email=request.new_email,
        token=token,
        user_nickname=active_user.nickname,
    )
 
    if not email_sent:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send confirmation email. Please try again later.",
        )
 
    return {"detail": "A confirmation email has been sent to your new email address."}
 
 
@router.get("/email/confirm", status_code=status.HTTP_200_OK)
def confirm_email_change(
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    """
    Confirm an email change using a token.
 
    Parameters:
        token (str): The email change token from the confirmation link.
        db (Session): The database session.
 
    Returns:
        Dict[str, str]: A confirmation message.
 
    Raises:
        HTTPException: If the token is invalid or expired.
    """
    
    user, old_email = user_crud.confirm_email_change(db, token)
 
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired email change token.",
        )
 
    if old_email:
        email_service.send_email_change_notification(
            old_email=old_email,
            new_email=user.email,
            user_nickname=user.nickname,
        )
 
    return {"detail": "Your email address has been updated successfully."}