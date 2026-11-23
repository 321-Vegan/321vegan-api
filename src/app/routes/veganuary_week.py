from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.crud.veganuary_week import veganuary_week_crud
from app.database.db import get_db
from app.log import get_logger
from app.models.veganuary_week import VeganuaryWeek
from app.routes.dependencies import RoleChecker, get_admin_or_client
from app.schemas.veganuary_week import (
    VeganuaryVersionOut,
    VeganuaryWeekIn,
    VeganuaryWeekOut,
)

log = get_logger(__name__)

router = APIRouter(dependencies=[Depends(get_admin_or_client)])


@router.get("/", response_model=List[VeganuaryWeekOut], status_code=status.HTTP_200_OK)
def fetch_veganuary_weeks(db: Session = Depends(get_db)) -> List[VeganuaryWeek]:
    """
    Fetch every week of the Veganuary course, in order.

    Returns:
        List[VeganuaryWeekOut]: Each week's number, last change and JSON.
    """
    return veganuary_week_crud.get_all_ordered(db)


@router.get("/version", response_model=VeganuaryVersionOut, status_code=status.HTTP_200_OK)
def fetch_veganuary_version(db: Session = Depends(get_db)) -> VeganuaryVersionOut:
    """
    Fetch the version of the course: the app downloads the weeks again only
    when it changes. Null while no week is stored (the app keeps its own).
    """
    return VeganuaryVersionOut(version=veganuary_week_crud.version(db))


@router.put(
    "/{number}",
    response_model=VeganuaryWeekOut,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(RoleChecker(["admin"]))],
)
def put_veganuary_week(
    number: int, week_in: VeganuaryWeekIn, db: Session = Depends(get_db)
) -> VeganuaryWeek:
    """
    Create or replace a week of the course.

    Only a quick check is made here: the app's tests (test/models/veganuary_test.dart)
    validate the whole content, run them on the JSON before sending it.

    Raises:
        HTTPException: If the JSON's number isn't the one of the URL, or it has no days.
    """
    content = week_in.content
    if content.get("number") != number:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"The JSON is for week {content.get('number')}, not {number}",
        )
    if not isinstance(content.get("days"), list) or not content["days"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A week needs its days",
        )
    try:
        return veganuary_week_crud.upsert(db, number, content)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Couldn't save week {number}. Error: {str(e)}",
        ) from e


@router.delete(
    "/{number}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(RoleChecker(["admin"]))],
)
def delete_veganuary_week(number: int, db: Session = Depends(get_db)):
    """
    Remove a week: the app goes back to its bundled copy of it.

    Raises:
        HTTPException: If the week isn't stored.
    """
    week = veganuary_week_crud.get_one(db, VeganuaryWeek.number == number)
    if week is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Veganuary week {number} not found",
        )
    veganuary_week_crud.delete(db, week)
