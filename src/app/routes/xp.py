from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.routes.dependencies import get_current_active_user_or_client, RoleChecker
from app.crud import xp_action_type_crud
from app.database.db import get_db
from app.log import get_logger
from app.schemas.xp import XPActionTypeOut, XPActionTypeUpdate

log = get_logger(__name__)

router = APIRouter()


@router.get(
    "/",
    response_model=List[Optional[XPActionTypeOut]],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(get_current_active_user_or_client)],
)
def fetch_xp_actions(db: Session = Depends(get_db)) -> List[Optional[XPActionTypeOut]]:
    """
    Fetch the catalog of XP-earning actions and their current values.

    Lets clients render an in-app "how to earn XP" legend without
    hardcoding values that admins can tune server-side.

    Parameters:
        db (Session): The database session.

    Returns:
        List[Optional[XPActionTypeOut]]: All configured XP action types.
    """
    return xp_action_type_crud.get_all(db)


@router.patch(
    "/{key}",
    response_model=XPActionTypeOut,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(RoleChecker(["admin"]))],
)
def update_xp_action(
    key: str,
    action_update: XPActionTypeUpdate,
    db: Session = Depends(get_db),
) -> XPActionTypeOut:
    """
    Tune an XP action's value, or enable/disable it, without a deploy.

    Admin only.

    Parameters:
        key (str): The action's stable key (e.g. "basic_scan").
        action_update (XPActionTypeUpdate): Fields to update.
        db (Session): The database session.

    Returns:
        XPActionTypeOut: The updated action type.

    Raises:
        HTTPException: If no action type has that key.
    """
    action_type = xp_action_type_crud.get_by_key(db, key)
    if action_type is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"XP action type with key '{key}' not found",
        )
    return xp_action_type_crud.update(db, action_type, action_update)
