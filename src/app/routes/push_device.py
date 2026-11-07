from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.database.db import get_db
from app.models.user import User
from app.routes.dependencies import get_current_active_user
from app.schemas.push_device import PushDeviceOut, PushDeviceRegister
from app.services.push_device import push_device_service


router = APIRouter()


@router.post(
    "/",
    response_model=PushDeviceOut,
    status_code=status.HTTP_200_OK,
)
def register_my_push_device(
    registration: PushDeviceRegister,
    db: Session = Depends(get_db),
    active_user: User = Depends(get_current_active_user),
) -> PushDeviceOut:
    """Register or refresh the current user's FCM destination."""
    return push_device_service.register(
        db,
        user_id=active_user.id,
        platform=registration.platform,
        installation_id=registration.installation_id,
        token=registration.token,
    )


@router.delete(
    "/{device_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def deactivate_my_push_device(
    device_id: int,
    db: Session = Depends(get_db),
    active_user: User = Depends(get_current_active_user),
) -> Response:
    """Deactivate an FCM destination during logout or notification opt-out."""
    if not push_device_service.deactivate(
        db,
        device_id=device_id,
        user_id=active_user.id,
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Push device with id {device_id} not found",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
