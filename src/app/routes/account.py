from typing import List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.routes.dependencies import get_current_active_user, get_pagination_params, get_sort_by_params
from app.crud import user_crud, b12_intake_crud, xp_event_crud
from app.crud.error_reports import error_report_crud
from app.database.db import get_db
from app.log import get_logger
from app.models import User
from app.schemas.b12_intake import B12IntakeOut
from app.schemas.error_report import ErrorReportOutPaginated
from app.schemas.xp import XPEventOutPaginated
from app.schemas.user import UserOut, UserUpdateOwn, DailyCheckinOut
from app.schemas.auth import EmailChangeRequest
from app.security import get_password_hash, verify_password
from app.services.email import email_service
from app.services.xp_service import award_xp, XPAction, DAILY_LOGIN_XP_CAP_DAYS
from app.services import avatar_service
from app.crud import avatar_crud, user_avatar_crud
from app.schemas.avatar import AvatarOut, AvatarPullOut

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

    dict_user_update = user_update.model_dump(
        exclude_unset=True
    )  # exclude_unset=True -
    # do not update fields with None
    if dict_user_update.get('avatar') is not None and not avatar_service.can_equip(
        db, active_user.id, dict_user_update['avatar']
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Avatar '{dict_user_update['avatar']}' is not unlocked",
        )
    try:
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


@router.get(
    "/xp-events",
    response_model=Optional[XPEventOutPaginated],
    status_code=status.HTTP_200_OK,
)
def fetch_my_xp_events(
    db: Session = Depends(get_db),
    pagination_params: Tuple[int, int] = Depends(get_pagination_params),
    active_user: User = Depends(get_current_active_user),
) -> Optional[XPEventOutPaginated]:
    """
    Fetch the current user's XP history, most recent first.

    Backs a future "recent XP gains" screen in the app.

    Parameters:
        db (Session): The database session.
        pagination_params (Tuple[int, int]): The pagination parameters (skip, limit).
        active_user (User): The current active user.

    Returns:
        Optional[XPEventOutPaginated]: The current user's XP events with pagination data.
    """
    page, size = pagination_params
    events, total = xp_event_crud.get_by_user(
        db, active_user.id, skip=page, limit=size)
    pages = (total + size - 1) // size
    return {
        "items": events,
        "total": total,
        "page": page,
        "size": size,
        "pages": pages,
    }


@router.post(
    "/check-in",
    response_model=DailyCheckinOut,
    status_code=status.HTTP_200_OK,
)
def daily_check_in(
    db: Session = Depends(get_db),
    active_user: User = Depends(get_current_active_user),
) -> DailyCheckinOut:
    """
    Record a daily check-in and award streak XP.

    Call once per app session/day. Calling again the same day is a safe
    no-op: the streak and XP are returned unchanged, nothing extra is
    awarded. Missing a day resets the streak to 1 on the next check-in.

    Parameters:
        db (Session): The database session.
        active_user (User): The current active user.

    Returns:
        DailyCheckinOut: The user's updated streak and any XP awarded.

    Raises:
        HTTPException: If the user is not found.
    """
    result = user_crud.record_daily_checkin(db, active_user.id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    xp_awarded = 0
    if result["is_new_day"]:
        quantity = min(result["streak_count"], DAILY_LOGIN_XP_CAP_DAYS)
        xp_awarded = award_xp(
            db, active_user, XPAction.DAILY_LOGIN,
            reference_type="login_streak", quantity=quantity,
        )

    return {
        "streak_count": result["streak_count"],
        "xp_awarded": xp_awarded,
        "level": active_user.level,
    }


@router.get(
    "/avatars",
    response_model=List[Optional[AvatarOut]],
    status_code=status.HTTP_200_OK,
)
def fetch_my_avatars(
    db: Session = Depends(get_db),
    active_user: User = Depends(get_current_active_user),
) -> List[Optional[AvatarOut]]:
    """
    Fetch the full avatar catalog with ownership for the current user.

    Every avatar is returned — including inactive ones, so an avatar a
    user already unlocked doesn't vanish from their collection just
    because it was later retired — annotated with `owned` (true for
    default avatars and any premium ones this user has unlocked). Backs
    a collection screen showing locked and unlocked avatars together,
    the same shape as the app's existing badges grid.

    Parameters:
        db (Session): The database session.
        active_user (User): The current active user.

    Returns:
        List[Optional[AvatarOut]]: The catalog, with `owned` set per avatar.
    """
    owned_ids = user_avatar_crud.get_owned_avatar_ids(db, active_user.id)
    avatars = []
    for avatar in avatar_crud.get_all(db):
        out = AvatarOut.model_validate(avatar)
        out.owned = avatar.is_default or avatar.id in owned_ids
        avatars.append(out)
    return avatars


@router.post(
    "/avatars/unlock",
    response_model=AvatarPullOut,
    status_code=status.HTTP_200_OK,
)
def unlock_avatar(
    db: Session = Depends(get_db),
    active_user: User = Depends(get_current_active_user),
) -> AvatarPullOut:
    """
    Spend one jeton on a weighted-random avatar pull.

    Duplicates are allowed: a pull can land on an avatar the user
    already owns, still spending the jeton (is_new=False in that case)
    so the configured odds never shift as a collection grows.

    Parameters:
        db (Session): The database session.
        active_user (User): The current active user.

    Returns:
        AvatarPullOut: The avatar won, whether it was new, and the
            user's remaining jeton balance.

    Raises:
        HTTPException: 402 if the user has no jetons to spend.
    """
    result = avatar_service.pull_avatar(db, active_user)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Not enough jetons to unlock an avatar",
        )
    return result


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