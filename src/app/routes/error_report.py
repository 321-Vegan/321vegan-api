from typing import Annotated, List, Optional, Tuple

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.routes.dependencies import get_current_active_user, get_current_active_user_or_client, get_pagination_params, get_sort_by_params, RoleChecker
from app.crud import user_crud
from app.crud.error_reports import error_report_crud
from app.database.db import get_db
from app.log import get_logger
from app.models import ApiClient, User
from app.models.error_report import ErrorReport
from app.schemas.error_report import ErrorReportCreate, ErrorReportOut, ErrorReportUpdate, ErrorReportOutPaginated, ErrorReportOutCount, ErrorReportFilters
from app.services.xp_service import award_xp, XPAction

log = get_logger(__name__)

router = APIRouter()


@router.get(
    "/",
    response_model=List[Optional[ErrorReportOut]],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(get_current_active_user)]
)
def fetch_all_error_reports(db: Session = Depends(get_db)) -> List[Optional[ErrorReportOut]]:
    """
    Fetch all error reports.

    This function fetches all error reports from the
    database.

    Parameters:
        db (Session): The database session.

    Returns:
        List[Optional[ErrorReportOut]]: The list of error reports fetched from the database.
    """
    return error_report_crud.get_all(db)


@router.get(
    "/count",
    response_model=Optional[ErrorReportOutCount],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(get_current_active_user)]
)
def fetch_count_error_reports(
    db: Session = Depends(get_db),
    filter_params: ErrorReportFilters = Depends(),
) -> Optional[ErrorReportOutCount]:
    """
    Fetch how many error reports.

    This function fetches total error report count from the
    database based on the filters parameters.

    Parameters:
        db (Session): The database session.
        filter_params (ErrorReportFilters): The filters parameters.

    Returns:
        Optional[ErrorReportOutCount]: The total count of error reports fetched from the database with filter datas.
    """
    total = error_report_crud.count(
        db,
        **filter_params.model_dump(exclude_none=True)
    )
    return {
        "total": total
    }


@router.get(
    "/search",
    response_model=Optional[ErrorReportOutPaginated],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(get_current_active_user)]
)
def fetch_paginated_error_reports(
    db: Session = Depends(get_db),
    pagination_params: Tuple[int, int] = Depends(get_pagination_params),
    orderby_params: Tuple[str, bool] = Depends(get_sort_by_params),
    filter_params: ErrorReportFilters = Depends(),
) -> Optional[ErrorReportOutPaginated]:
    """
    Fetch many error reports.

    This function fetches all error reports from the
    database based on the pagination parameters.

    Parameters:
        db (Session): The database session.
        pagination_params (Tuple[int, int]): The pagination parameters (skip, limit).
        orderby_params (Tuple[str, bool]): The order by parameters (sortby, descending).

    Returns:
        Optional[ErrorReportOutPaginated]: The list of error reports fetched from the database with pagination datas.
    """
    page, size = pagination_params
    sortby, descending = orderby_params
    error_reports, total = error_report_crud.get_many(
        db,
        skip=page,
        limit=size,
        order_by=sortby,
        descending=descending,
        **filter_params.model_dump(exclude_none=True)
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
    "/{id}",
    response_model=Optional[ErrorReportOut],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(get_current_active_user)]
)
def fetch_error_report_by_id(
    id: int, db: Session = Depends(get_db)
) -> ErrorReportOut:
    """
    Fetches an error report by its ID.

    Parameters:
        id (int): The ID of the error report.
        db (Session): The database session.

    Returns:
        ErrorReportOut: The fetched error report.

    Raises:
        HTTPException: If the error report is not found.
    """
    error_report = error_report_crud.get_one(db, ErrorReport.id == id)
    if error_report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Error report with id {id} not found",
        )
    return error_report


@router.post(
    "/",
    response_model=ErrorReportOut,
    status_code=status.HTTP_201_CREATED,
    response_model_exclude_none=True,
    response_model_exclude_unset=True,
    dependencies=[Depends(get_current_active_user_or_client)]
)
def create_error_report(
    error_report_create: Annotated[
        ErrorReportCreate,
        Body(
            examples=[
                {
                    "ean": "1234567890123",
                    "comment": "This product information seems incorrect",
                    "contact": "user@example.com",
                    "handled": False,
                }
            ]
        ),
    ],
    db: Session = Depends(get_db),
    current_user_or_client: User | ApiClient = Depends(
        get_current_active_user_or_client),
):
    """
    Create an error report.

    Parameters:
        error_report_create (ErrorReportCreate): The error report data to be created.
        db (Session, optional): The database session.
            Defaults to Depends(get_db).
        current_user_or_client (User | ApiClient): The current active user or API client.

    Returns:
        ErrorReportOut: The created error report.

    Raises:
        HTTPException: If there is an error creating
            the error report in the database.
    """
    try:
        error_report = error_report_crud.create(
            db, error_report_create
        )
    except IntegrityError as e:
        error_message = str(e.orig)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Data integrity error: {error_message}",
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Couldn't create error report. Error: {str(e)}",
        ) from e

    user = None
    if isinstance(current_user_or_client, User):
        user = current_user_or_client
    elif error_report_create.created_by is not None:
        user = user_crud.get_one(db, User.id == error_report_create.created_by)

    xp_awarded = 0
    if user:
        xp_awarded = award_xp(
            db, user, XPAction.ERROR_REPORT,
            reference_type="error_report", reference_id=error_report.id,
        )
    error_report.xp_awarded = xp_awarded
    error_report.level = user.level if user else None
    return error_report


@router.put(
    "/{id}",
    response_model=ErrorReportOut,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(RoleChecker(["contributor", "admin"]))]
)
def update_error_report(
    id: int,
    error_report_update: ErrorReportUpdate,
    db: Session = Depends(get_db)
):
    """
    Update an error report by its ID.

    Parameters:
        id (int): The ID of the error report to be updated.
        error_report_update (ErrorReportUpdate): The updated error report data.
        db (Session, optional): The database session.
            Defaults to Depends(get_db).

    Returns:
        ErrorReportOut: The updated error report.

    Raises:
        HTTPException: If the error report does not exist or
            the user does not have enough permissions.
        HTTPException: If there is an error updating
            the error report in the database.
    """
    error_report = error_report_crud.get_one(db, ErrorReport.id == id)
    if error_report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Error report with id {id} not found",
        )

    try:
        error_report = error_report_crud.update(
            db, error_report, error_report_update)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Couldn't update error report with id {id}. Error: {str(e)}",
        ) from e
    return error_report


@router.delete("/{id}",
               status_code=status.HTTP_204_NO_CONTENT,
               dependencies=[Depends(RoleChecker(["contributor", "admin"]))])
def delete_error_report(
    id: int,
    db: Session = Depends(get_db)
):
    """
    Deletes an error report by its ID.

    Parameters:
        id (int): The ID of the error report to delete.
        db (Session): The database session.

    Returns:
        dict: A dictionary containing the detail that
            the error report with the given ID was deleted.

    Raises:
        HTTPException: If the error report with the given ID is not found.
        HTTPException: If the user does not have enough
            permissions to delete the error report.
        HTTPException: If there is an error while
            deleting the error report from the database.
    """
    error_report = error_report_crud.get_one(db, ErrorReport.id == id)
    if error_report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Error report with id {id} not found. Cannot delete.",
        )

    try:
        error_report_crud.delete(db, error_report)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Couldn't delete error report with id {id}. Error: {str(e)}",
        ) from e
