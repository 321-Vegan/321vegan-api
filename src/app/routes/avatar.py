from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.routes.dependencies import get_current_active_user_or_client, RoleChecker
from app.crud import avatar_crud
from app.database.db import get_db
from app.log import get_logger
from app.schemas.avatar import AvatarOut, AvatarUpdate

log = get_logger(__name__)

router = APIRouter()


@router.get(
    "/",
    response_model=List[Optional[AvatarOut]],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(get_current_active_user_or_client)],
)
def fetch_avatars(db: Session = Depends(get_db)) -> List[Optional[AvatarOut]]:
    """
    Fetch the full avatar catalog (default and premium, active and not).

    Parameters:
        db (Session): The database session.

    Returns:
        List[Optional[AvatarOut]]: All configured avatars.
    """
    return avatar_crud.get_all(db)


@router.patch(
    "/{key}",
    response_model=AvatarOut,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(RoleChecker(["admin"]))],
)
def update_avatar(
    key: str,
    avatar_update: AvatarUpdate,
    db: Session = Depends(get_db),
) -> AvatarOut:
    """
    Tune an avatar's pull weight, label, or active state. Admin only.

    Parameters:
        key (str): The avatar's stable key (e.g. "legendary_fox.png").
        avatar_update (AvatarUpdate): Fields to update.
        db (Session): The database session.

    Returns:
        AvatarOut: The updated avatar.

    Raises:
        HTTPException: If no avatar has that key.
    """
    avatar = avatar_crud.get_by_key(db, key)
    if avatar is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Avatar with key '{key}' not found",
        )
    return avatar_crud.update(db, avatar, avatar_update)
