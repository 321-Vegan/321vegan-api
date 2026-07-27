from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime, timezone
from app.models.shop_review import ShopReviewStatus


class UserOut(BaseModel):
    id: int
    nickname: str
    avatar: Optional[str] = None


class ShopOut(BaseModel):
    id: int
    name: str
    latitude: float
    longitude: float
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    shop_type: Optional[str] = None


class ShopReviewCreate(BaseModel):
    shop_id: int
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = None
    user_id: Optional[int] = None


class ShopReviewUpdate(BaseModel):
    rating: Optional[int] = Field(None, ge=1, le=5)
    comment: Optional[str] = None


class ShopReviewStatusUpdate(BaseModel):
    status: str


class ShopReviewOut(BaseModel):
    id: int
    shop_id: int
    shop: ShopOut
    user_id: Optional[int] = None
    user_nickname: Optional[str] = None
    user: UserOut
    rating: int
    comment: Optional[str] = None
    status: str
    created_at: datetime
    xp_awarded: Optional[int] = None

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%z"),
        }


class ShopReviewOutPaginated(BaseModel):
    items: list[ShopReviewOut]
    total: int
    page: int
    size: int
    pages: int


class ShopReviewSummaryOut(BaseModel):
    shop_id: int
    review_count: int
    rating_avg: float


class ShopReviewOutCount(BaseModel):
    total: int


class ShopReviewFilters(BaseModel):
    """Filters for shop reviews search."""
    shop_id: Optional[int] = None
    shop___name__ilike: Optional[str] = None
    shop___name__contains: Optional[str] = None
    user_id: Optional[int] = None
    user___nickname__contains: Optional[str] = None
    status: Optional[str] = None
    status__ne: Optional[str] = None
    comment__contains: Optional[str] = None
    rating: Optional[str] = None
    created_at: Optional[str] = None
    created_at__gt: Optional[str] = None
