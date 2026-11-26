from typing import List

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database.db import get_db
from app.log import get_logger
from app.models.user import User
from app.routes.dependencies import RoleChecker, get_current_active_user
from app.schemas.notification_broadcast import (
    NotificationBroadcastIn,
    NotificationBroadcastOut,
    NotificationBroadcastRecipientsOut,
)
from app.services.notification_broadcast import notification_broadcast_service

log = get_logger(__name__)

# The admin tool's notifications page
router = APIRouter(dependencies=[Depends(RoleChecker(["admin"]))])


@router.get(
    "/",
    response_model=List[NotificationBroadcastOut],
    status_code=status.HTTP_200_OK,
)
def fetch_notification_broadcasts(
    db: Session = Depends(get_db),
) -> List[dict]:
    """
    The last notifications sent to everyone, newest first, with how many
    were read and how the pushes went.
    """
    return notification_broadcast_service.list_with_stats(db)


@router.get(
    "/recipients",
    response_model=NotificationBroadcastRecipientsOut,
    status_code=status.HTTP_200_OK,
)
def fetch_notification_broadcast_recipients(
    db: Session = Depends(get_db),
) -> NotificationBroadcastRecipientsOut:
    """
    How many accounts a notification sent now would reach: active ones with
    at least one device taking pushes.
    """
    return NotificationBroadcastRecipientsOut(
        count=len(notification_broadcast_service.recipient_ids(db)),
    )


@router.post(
    "/",
    response_model=NotificationBroadcastOut,
    status_code=status.HTTP_201_CREATED,
)
def send_notification_broadcast(
    broadcast_in: NotificationBroadcastIn,
    db: Session = Depends(get_db),
    active_user: User = Depends(get_current_active_user),
) -> NotificationBroadcastOut:
    """
    Send a notification to every account with pushes turned on: in their
    notification center, and as a push (sent by the FCM worker).
    """
    broadcast = notification_broadcast_service.send(
        db,
        title=broadcast_in.title,
        body=broadcast_in.body,
        sent_by_id=active_user.id,
    )
    log.info(
        "Broadcast %s sent by %s to %s accounts",
        broadcast.id, active_user.id, broadcast.recipient_count,
    )
    return NotificationBroadcastOut(
        id=broadcast.id,
        title=broadcast.title,
        body=broadcast.body,
        recipient_count=broadcast.recipient_count,
        sent_by=active_user.nickname,
        created_at=broadcast.created_at,
        pushes_pending=0,
    )
