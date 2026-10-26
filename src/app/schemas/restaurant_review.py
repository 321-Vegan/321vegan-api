from pydantic import BaseModel, Field
from typing import Dict, List, Optional
from datetime import datetime, timezone
from app.models.restaurant_review import RestaurantPriceRange, RestaurantReviewStatus
from app.schemas.restaurant import RestaurantPhotoOut

# Detailed ratings, by summary key
CRITERIA = {
    "choice": "rating_choice",
    "value": "rating_value",
    "taste": "rating_taste",
    "service": "rating_service",
}


class UserOut(BaseModel):
    id: int
    nickname: str
    avatar: Optional[str] = None
    is_premium: bool = False


class RestaurantOut(BaseModel):
    id: int
    name: str
    city: Optional[str] = None
    vegan_status: str
    tags: List[str]


class RestaurantReviewCreate(BaseModel):
    restaurant_id: int
    # Overall experience, the rating shown on the map
    rating: int = Field(..., ge=1, le=5)
    rating_choice: Optional[int] = Field(None, ge=1, le=5)
    rating_value: Optional[int] = Field(None, ge=1, le=5)
    rating_taste: Optional[int] = Field(None, ge=1, le=5)
    rating_service: Optional[int] = Field(None, ge=1, le=5)
    # Price per person
    price_range: Optional[RestaurantPriceRange] = None
    comment: Optional[str] = Field(None, max_length=2000)
    user_id: Optional[int] = None
    status: Optional[RestaurantReviewStatus] = None


class RestaurantReviewUpdate(BaseModel):
    rating: Optional[int] = Field(None, ge=1, le=5)
    rating_choice: Optional[int] = Field(None, ge=1, le=5)
    rating_value: Optional[int] = Field(None, ge=1, le=5)
    rating_taste: Optional[int] = Field(None, ge=1, le=5)
    rating_service: Optional[int] = Field(None, ge=1, le=5)
    price_range: Optional[RestaurantPriceRange] = None
    comment: Optional[str] = Field(None, max_length=2000)


class RestaurantReviewStatusUpdate(BaseModel):
    status: RestaurantReviewStatus


class RestaurantReviewOut(BaseModel):
    id: int
    restaurant_id: int
    restaurant: RestaurantOut
    user_id: Optional[int] = None
    user_nickname: Optional[str] = None
    user_is_premium: bool = False
    user: Optional[UserOut] = None
    rating: int
    rating_choice: Optional[int] = None
    rating_value: Optional[int] = None
    rating_taste: Optional[int] = None
    rating_service: Optional[int] = None
    price_range: Optional[str] = None
    comment: Optional[str] = None
    status: str
    photos: List[RestaurantPhotoOut] = []
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%z"),
        }


class RestaurantReviewOutPaginated(BaseModel):
    items: list[RestaurantReviewOut]
    total: int
    page: int
    size: int
    pages: int


class CriterionSummaryOut(BaseModel):
    rating_avg: Optional[float] = None
    rating_count: int = 0


class RestaurantReviewSummaryOut(BaseModel):
    restaurant_id: int
    review_count: int
    comment_count: int
    # Average of the overall experience only
    rating_avg: float
    # Number of approved reviews per overall rating, e.g. {"1": 0, ..., "5": 12}
    rating_distribution: Dict[str, int]
    # Detailed ratings, keyed by choice / value / taste / service
    criteria: Dict[str, CriterionSummaryOut]
    # Price per person most chosen in the reviews (ties: the cheaper), null
    # when no review gave one
    price_range: Optional[str] = None
    # Number of approved reviews per price range, e.g. {"UNDER_10": 2, ...}
    price_range_distribution: Dict[str, int] = {}


class RestaurantReviewOutCount(BaseModel):
    total: int


class RestaurantReviewFilters(BaseModel):
    """Filters for restaurant reviews search."""
    restaurant_id: Optional[int] = None
    restaurant___name__ilike: Optional[str] = None
    restaurant___name__contains: Optional[str] = None
    user_id: Optional[int] = None
    user___nickname__contains: Optional[str] = None
    status: Optional[str] = None
    status__ne: Optional[str] = None
    comment__contains: Optional[str] = None
    comment__isnull: Optional[bool] = None
    rating: Optional[str] = None
    created_at: Optional[str] = None
    created_at__gt: Optional[str] = None
