import math
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.routes.dependencies import (
    get_current_active_user,
    get_current_client,
    get_current_superuser,
    get_pagination_params,
)
from app.crud.subscription import subscription_crud
from app.database.db import get_db
from app.log import get_logger
from app.models import User
from app.schemas.subscription import (
    SubscriptionVerifyRequest,
    SubscriptionOut,
    SubscriptionEventOut,
    SubscriptionEventOutPaginated,
)
from app.services.subscription_service import subscription_service

log = get_logger(__name__)

router = APIRouter()


@router.post("/verify", response_model=SubscriptionOut, status_code=status.HTTP_200_OK)
def verify_subscription(
    request: SubscriptionVerifyRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """
    Verify an in-app purchase receipt and create/update the user's subscription.
    Called by the Flutter app after a successful purchase.
    """
    subscription = subscription_service.process_verification(
        db=db,
        user_id=user.id,
        platform=request.platform,
        transaction_id=request.transaction_id,
        purchase_token=request.purchase_token,
        product_id=request.product_id,
    )
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Subscription verification failed",
        )
    return subscription


@router.get("/count", status_code=status.HTTP_200_OK)
def get_active_subscription_count(
    db: Session = Depends(get_db),
    _client=Depends(get_current_client),
):
    """Return the number of active subscribers, useful for displaying a community goal."""
    count = subscription_crud.count_active(db)
    return {"count": count}


@router.get("/me", response_model=SubscriptionOut, status_code=status.HTTP_200_OK)
def get_my_subscription(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
):
    """Return the current user's latest subscription."""
    subscription = subscription_crud.get_by_user_id(db, user.id)
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No subscription found",
        )
    return subscription


@router.get("/me/events", response_model=SubscriptionEventOutPaginated, status_code=status.HTTP_200_OK)
def get_my_subscription_events(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_active_user),
    pagination: tuple = Depends(get_pagination_params),
):
    """Return the event history for the current user's subscription."""
    subscription = subscription_crud.get_by_user_id(db, user.id)
    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No subscription found",
        )
    skip, size = pagination
    items, total = subscription_crud.get_events_by_subscription_id(
        db, subscription.id, skip=skip, limit=size
    )
    pages = math.ceil(total / size) if size > 0 else 0
    return SubscriptionEventOutPaginated(
        items=items,
        total=total,
        page=(skip // size) + 1 if size > 0 else 1,
        size=size,
        pages=pages,
    )


@router.get("/admin/diagnostics", status_code=status.HTTP_200_OK)
def get_subscription_diagnostics(
    db: Session = Depends(get_db),
    _admin: User = Depends(get_current_superuser),
):
    """
    Admin-only: compare every active/grace_period subscription against its
    platform's live status (Apple/Google) and report any drift. Read-only.

    Slow by nature (one external API call per subscription) -- call on
    demand, don't poll it. See run_subscription_diagnostics() docstring for
    what it can and can't catch.
    """
    issues = subscription_service.run_subscription_diagnostics(db)
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "issue_count": len(issues),
        "issues": issues,
    }
