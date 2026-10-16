from pydantic import BaseModel, Field, model_validator
from typing import Dict, Optional
from datetime import datetime, timezone
from app.models.product_review import ProductReviewStatus


class UserOut(BaseModel):
    id: int
    nickname: str
    avatar: Optional[str] = None
    is_premium: bool = False


class ProductOut(BaseModel):
    id: int
    ean: str
    name: Optional[str] = None
    brand_name: Optional[str] = None
    image: Optional[str] = None
    status: Optional[str] = None
    product_type: Optional[str] = None


class ProductReviewCreate(BaseModel):
    # One of product_id or ean is required
    product_id: Optional[int] = None
    ean: Optional[str] = None
    rating: int = Field(..., ge=0, le=5)
    comment: Optional[str] = Field(None, max_length=2000)
    user_id: Optional[int] = None
    status: Optional[ProductReviewStatus] = None

    @model_validator(mode="after")
    def check_product_reference(self):
        if self.product_id is None and not self.ean:
            raise ValueError("product_id or ean is required")
        return self


class ProductReviewUpdate(BaseModel):
    rating: Optional[int] = Field(None, ge=0, le=5)
    comment: Optional[str] = Field(None, max_length=2000)
    status: Optional[ProductReviewStatus] = None


class ProductReviewStatusUpdate(BaseModel):
    status: ProductReviewStatus


class ProductReviewOut(BaseModel):
    id: int
    product_id: int
    product: ProductOut
    user_id: Optional[int] = None
    user_nickname: Optional[str] = None
    user_is_premium: bool = False
    user: Optional[UserOut] = None
    rating: int
    comment: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%z"),
        }


class ProductReviewOutPaginated(BaseModel):
    items: list[ProductReviewOut]
    total: int
    page: int
    size: int
    pages: int


class ProductReviewSummaryOut(BaseModel):
    product_id: int
    review_count: int
    comment_count: int
    rating_avg: float
    # Number of approved reviews per rating value, e.g. {"0": 0, ..., "5": 12}
    rating_distribution: Dict[str, int]


class ProductReviewOutCount(BaseModel):
    total: int


class ProductReviewFilters(BaseModel):
    """Filters for product reviews search."""
    product_id: Optional[int] = None
    product___ean: Optional[str] = None
    product___name__ilike: Optional[str] = None
    product___name__contains: Optional[str] = None
    user_id: Optional[int] = None
    user___nickname__contains: Optional[str] = None
    status: Optional[str] = None
    status__ne: Optional[str] = None
    comment__contains: Optional[str] = None
    comment__isnull: Optional[bool] = None
    rating: Optional[str] = None
    created_at: Optional[str] = None
    created_at__gt: Optional[str] = None
