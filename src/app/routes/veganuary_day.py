from datetime import date, timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.crud.veganuary_day import veganuary_day_crud
from app.database.db import get_db
from app.models.user import User
from app.models.veganuary_day import VeganuaryDay
from app.routes.dependencies import get_current_active_user
from app.schemas.veganuary_day import (
    VEGANUARY_DAYS,
    VeganuaryDayIn,
    VeganuaryDayOut,
)

router = APIRouter()


@router.get("", response_model=List[VeganuaryDayOut], status_code=status.HTTP_200_OK)
def fetch_my_veganuary_days(
    db: Session = Depends(get_db),
    active_user: User = Depends(get_current_active_user),
) -> List[VeganuaryDay]:
    """
    The days of the Veganuary course the current user has done, in order.
    """
    return veganuary_day_crud.get_by_user(db, active_user.id)


@router.put(
    "/{day}", response_model=VeganuaryDayOut, status_code=status.HTTP_200_OK
)
def save_my_veganuary_day(
    day: int,
    day_in: VeganuaryDayIn,
    db: Session = Depends(get_db),
    active_user: User = Depends(get_current_active_user),
) -> VeganuaryDay:
    """
    Record a day of the course as done by the current user. Can be sent
    again (a retry, another device): the earliest date is kept, so is the
    idée reçue already known when none is sent.

    Raises:
        HTTPException: 400 if the day isn't one of the course, or its date is
            in the future.
    """
    if not 1 <= day <= VEGANUARY_DAYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Day {day} isn't a day of the course",
        )
    # The user's local date: up to a day ahead of the server's
    if day_in.completed_on > date.today() + timedelta(days=1):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{day_in.completed_on} is in the future",
        )
    return veganuary_day_crud.save(
        db, active_user.id, day, day_in.completed_on, day_in.myth_id
    )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def reset_my_veganuary_days(
    db: Session = Depends(get_db),
    active_user: User = Depends(get_current_active_user),
):
    """
    Start the course over: forget every day the current user has done.
    """
    veganuary_day_crud.delete_by_user(db, active_user.id)
