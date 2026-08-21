from typing import Optional, List
from pydantic import BaseModel, EmailStr
from datetime import datetime, timezone


class SubscriptionVerifyRequest(BaseModel):
    platform: str
    transaction_id: Optional[str] = None
    purchase_token: Optional[str] = None
    product_id: str


class AdminSubscriptionVerifyRequest(SubscriptionVerifyRequest):
    """Same as SubscriptionVerifyRequest, but for an admin verifying on behalf of a user
    who can't (e.g. their client never sent the initial purchase receipt)."""
    user_email: EmailStr


class SubscriptionOut(BaseModel):
    id: int
    user_id: int
    platform: str
    original_transaction_id: str
    product_id: str
    status: str
    expires_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%z"),
        }


class SubscriptionEventOut(BaseModel):
    id: int
    event_type: str
    platform_event_data: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%z"),
        }


class SubscriptionEventOutPaginated(BaseModel):
    items: List[SubscriptionEventOut]
    total: int
    page: int
    size: int
    pages: int


# Webhook schemas

class AppleNotificationPayload(BaseModel):
    signedPayload: str


class GooglePubSubMessage(BaseModel):
    data: str
    message_id: Optional[str] = None
    publish_time: Optional[str] = None


class GooglePubSubPayload(BaseModel):
    message: GooglePubSubMessage
    subscription: Optional[str] = None
