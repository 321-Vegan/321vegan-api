from typing import Annotated, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.routes.dependencies import (
    get_admin_or_client,
    get_current_active_user,
    get_current_active_user_or_client,
)
from app.crud import b12_intake_crud
from app.database.db import get_db
from app.log import get_logger
from app.models import User, ApiClient
from app.schemas.b12_intake import B12IntakeCreate, B12IntakeOut
from app.services.xp_service import award_xp, XPAction

log = get_logger(__name__)

router = APIRouter(dependencies=[Depends(get_current_active_user_or_client)])


@router.post(
    "/",
    response_model=B12IntakeOut,
    status_code=status.HTTP_201_CREATED,
)
def create_b12_intake(
    intake_create: Annotated[
        B12IntakeCreate,
        Body(
            examples=[
                {
                    "intake_date": "2026-07-13",
                    "frequency": "weekly",
                }
            ]
        ),
    ],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Record a B12 intake for the current user on a given day.

    The intake always belongs to the authenticated user: it is recorded
    for the token's user, and the caller cannot record an intake for
    somebody else. Requires a user token
    A user has at most one intake per day: recording the same day again
    returns 409 so clients can safely retry queued (offline) intakes.

    Parameters:
        intake_create (B12IntakeCreate): The intake data (intake_date, frequency).
        db (Session): The database session.
        current_user (User): The current active user the intake is recorded for.

    Returns:
        B12IntakeOut: The created intake.

    Raises:
        HTTPException: 409 if the intake is already recorded for that day.
        HTTPException: 400 if the user does not exist.
    """
    intake_create.user_id = current_user.id
    try:
        intake = b12_intake_crud.create(db, intake_create)
    except IntegrityError as e:
        db.rollback()
        error_message = str(e.orig)
        if "uq_b12_intake_user_date" in error_message:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"B12 intake already recorded for user {intake_create.user_id} on {intake_create.intake_date}",
            ) from e
        if "foreign key constraint" in error_message.lower() and "user_id" in error_message.lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"User with id {intake_create.user_id} does not exist",
            ) from e
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Data integrity error: {error_message}",
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Couldn't create B12 intake. Error: {str(e)}",
        ) from e

    intake.xp_awarded = award_xp(
        db, current_user, XPAction.B12_INTAKE,
        reference_type="b12_intake", reference_id=intake.id,
    )
    return intake


@router.get(
    "/user/{user_id}",
    response_model=List[Optional[B12IntakeOut]],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(get_admin_or_client)],
)
def fetch_b12_intakes_by_user(
    user_id: int, db: Session = Depends(get_db)
) -> List[Optional[B12IntakeOut]]:
    """
    Fetch all B12 intakes of a user, most recent first.

    Restricted to admin users and API clients. Regular users fetch
    their own intakes through GET /me/b12-intakes.

    Parameters:
        user_id (int): The user ID.
        db (Session): The database session.

    Returns:
        List[Optional[B12IntakeOut]]: The user's B12 intakes.
    """
    return b12_intake_crud.get_by_user(db, user_id)
