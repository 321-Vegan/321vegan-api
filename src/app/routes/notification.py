from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.crud.notification import notification_crud
from app.database.db import get_db
from app.models.user import User
from app.routes.dependencies import get_current_active_user
from app.schemas.notification import NotificationOut


router = APIRouter()


@router.get(
    "/",
    response_model=list[NotificationOut],
    status_code=status.HTTP_200_OK,
)
def fetch_my_notifications(
    after_id: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    db: Session = Depends(get_db),
    active_user: User = Depends(get_current_active_user),
) -> list[NotificationOut]:
    """Return the current user's notifications after an incremental cursor."""
    return notification_crud.get_since(
        db,
        user_id=active_user.id,
        after_id=after_id,
        limit=limit,
    )


@router.patch(
    "/{notification_id}/read",
    status_code=status.HTTP_204_NO_CONTENT,
)
def mark_my_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    active_user: User = Depends(get_current_active_user),
) -> Response:
    """Delete an owned notification and its deliveries; always acknowledge with 204."""
    notification_crud.delete_for_user(
        db,
        notification_id=notification_id,
        user_id=active_user.id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
