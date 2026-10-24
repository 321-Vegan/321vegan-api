from datetime import date, datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.models.restaurant import RestaurantVeganStatus, RestaurantOperatingStatus, RestaurantTag
from app.models.restaurant_photo import RestaurantPhotoStatus

TIME_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"
MINUTES_PER_DAY = 24 * 60
MINUTES_PER_WEEK = 7 * MINUTES_PER_DAY
MAX_PLANT_MILK_SURCHARGE = 5
CONTACT_FIELDS = ("phone", "website", "facebook", "instagram")
TEXT_FIELDS = ("name", "address", "city", "country", "description",
               "vegan_options_details", "service_area", "opening_hours_note",
               "phone", "website", "facebook", "instagram", "closure_note")


def _to_minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


class OpeningSlot(BaseModel):
    """One opening slot; close < open means the slot ends after midnight."""
    day: int = Field(..., ge=0, le=6, description="0 = monday, 6 = sunday")
    open: str = Field(..., pattern=TIME_PATTERN)
    close: str = Field(..., pattern=TIME_PATTERN)

    @model_validator(mode="after")
    def check_not_empty(self):
        if self.open == self.close:
            raise ValueError("A slot cannot open and close at the same time")
        return self

    def week_interval(self) -> tuple[int, int]:
        """Start and end of the slot in minutes since monday 00:00."""
        start = self.day * MINUTES_PER_DAY + _to_minutes(self.open)
        duration = (_to_minutes(self.close) -
                    _to_minutes(self.open)) % MINUTES_PER_DAY
        return start, start + duration


def _check_no_overlap(slots: List[OpeningSlot]) -> None:
    """Slots may not overlap, including a slot running past midnight."""
    intervals = sorted(slot.week_interval() for slot in slots)
    for (_, previous_end), (start, _) in zip(intervals, intervals[1:]):
        if start < previous_end:
            raise ValueError("Opening slots overlap")
    # A sunday slot running past midnight must not overlap monday's first one
    if intervals and intervals[-1][1] - MINUTES_PER_WEEK > intervals[0][0]:
        raise ValueError("Opening slots overlap")


class RestaurantBase(BaseModel):
    """
    Full restaurant data, with the business rules. Used to create a
    restaurant and to check the merged state of an update.
    """
    model_config = ConfigDict(use_enum_values=True)

    name: str = Field(..., min_length=1, max_length=200)
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    description: Optional[str] = Field(None, max_length=5000)
    vegan_status: RestaurantVeganStatus
    vegan_options_details: Optional[str] = Field(None, max_length=2000)
    tags: List[RestaurantTag] = Field(..., min_length=1)
    plant_milk_surcharge: Optional[float] = Field(
        None, ge=-MAX_PLANT_MILK_SURCHARGE, le=MAX_PLANT_MILK_SURCHARGE)
    has_storefront: bool = True
    service_area: Optional[str] = Field(None, max_length=200)
    opening_hours: Optional[List[OpeningSlot]] = None
    opening_hours_note: Optional[str] = Field(None, max_length=500)
    phone: Optional[str] = Field(None, max_length=50)
    website: Optional[str] = Field(None, max_length=500)
    facebook: Optional[str] = Field(None, max_length=500)
    instagram: Optional[str] = Field(None, max_length=500)
    operating_status: RestaurantOperatingStatus = RestaurantOperatingStatus.OPEN
    closed_from: Optional[date] = None
    closed_until: Optional[date] = None
    closure_note: Optional[str] = Field(None, max_length=500)

    @field_validator(*TEXT_FIELDS, mode="before")
    @classmethod
    def strip_text(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("tags")
    @classmethod
    def dedupe_tags(cls, tags):
        return list(dict.fromkeys(tags))

    @field_validator("plant_milk_surcharge")
    @classmethod
    def round_surcharge(cls, value):
        return round(value, 2) if value is not None else None

    @field_validator("opening_hours")
    @classmethod
    def check_opening_hours(cls, slots):
        if slots:
            _check_no_overlap(slots)
        return slots

    @model_validator(mode="after")
    def check_rules(self):
        if self.vegan_status == RestaurantVeganStatus.VEGAN_OPTIONS and not self.vegan_options_details:
            raise ValueError(
                "vegan_options_details is required when the place is not fully vegan")

        if not self.has_storefront:
            if RestaurantTag.CATERER not in self.tags:
                raise ValueError(
                    "Only a caterer can have no storefront")
            if not self.service_area:
                raise ValueError(
                    "service_area is required without a storefront")
            if not any(getattr(self, field) for field in CONTACT_FIELDS):
                raise ValueError(
                    "A phone, website, facebook or instagram is required without a storefront")
            # Many caterers work from home: never keep a precise position
            # (2 decimals is about 1 km)
            self.latitude = round(self.latitude, 2)
            self.longitude = round(self.longitude, 2)

        if self.operating_status != RestaurantOperatingStatus.TEMPORARILY_CLOSED:
            if self.closed_from or self.closed_until:
                raise ValueError(
                    "closed_from and closed_until are only for a temporary closure")
        elif self.closed_from and self.closed_until and self.closed_from > self.closed_until:
            raise ValueError("closed_from must be before closed_until")
        return self


class RestaurantCreate(RestaurantBase):
    pass


class RestaurantUpdate(BaseModel):
    """
    Partial update. The business rules are checked on the restaurant merged
    with these changes (see RestaurantBase).
    """
    model_config = ConfigDict(use_enum_values=True)

    name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    description: Optional[str] = None
    vegan_status: Optional[RestaurantVeganStatus] = None
    vegan_options_details: Optional[str] = None
    tags: Optional[List[RestaurantTag]] = None
    plant_milk_surcharge: Optional[float] = None
    has_storefront: Optional[bool] = None
    service_area: Optional[str] = None
    opening_hours: Optional[List[OpeningSlot]] = None
    opening_hours_note: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    facebook: Optional[str] = None
    instagram: Optional[str] = None
    operating_status: Optional[RestaurantOperatingStatus] = None
    closed_from: Optional[date] = None
    closed_until: Optional[date] = None
    closure_note: Optional[str] = None
    # Moderators only
    validated: Optional[bool] = None


class RestaurantPhotoOut(BaseModel):
    id: int
    restaurant_id: int
    review_id: Optional[int] = None
    kind: Optional[str] = None
    path: str
    status: str
    user_id: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%z"),
        }


class RestaurantPhotoStatusUpdate(BaseModel):
    status: RestaurantPhotoStatus


class RestaurantBriefOut(BaseModel):
    id: int
    name: str
    city: Optional[str] = None
    vegan_status: str
    validated: bool


class RestaurantPhotoWithRestaurantOut(RestaurantPhotoOut):
    restaurant: RestaurantBriefOut


class RestaurantPhotoOutPaginated(BaseModel):
    items: list[RestaurantPhotoWithRestaurantOut]
    total: int
    page: int
    size: int
    pages: int


class RestaurantPhotoFilters(BaseModel):
    """Filters for restaurant place and menu photos search."""
    restaurant_id: Optional[int] = None
    restaurant___name__contains: Optional[str] = None
    kind: Optional[str] = None
    status: Optional[str] = None
    user_id: Optional[int] = None


class RestaurantOut(BaseModel):
    id: int
    name: str
    latitude: float
    longitude: float
    address: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    description: Optional[str] = None
    vegan_status: str
    vegan_options_details: Optional[str] = None
    tags: List[str]
    plant_milk_surcharge: Optional[float] = None
    has_storefront: bool
    service_area: Optional[str] = None
    opening_hours: Optional[List[OpeningSlot]] = None
    opening_hours_note: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    facebook: Optional[str] = None
    instagram: Optional[str] = None
    operating_status: str
    closed_from: Optional[date] = None
    closed_until: Optional[date] = None
    closure_note: Optional[str] = None
    is_closed_now: bool
    osm_id: Optional[str] = None
    created_by: Optional[int] = None
    validated: bool
    created_at: datetime
    updated_at: datetime
    photos: List[RestaurantPhotoOut] = []

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%z"),
        }


class RestaurantMapOut(BaseModel):
    """Light restaurant data for the map pins."""
    id: int
    name: str
    latitude: float
    longitude: float
    vegan_status: str
    tags: List[str]
    has_storefront: bool
    plant_milk_surcharge: Optional[float] = None
    # For the "open now" filter of the map
    opening_hours: Optional[List[OpeningSlot]] = None
    operating_status: str
    is_closed_now: bool
    validated: bool
    rating_avg: Optional[float] = None
    review_count: int = 0

    class Config:
        from_attributes = True


class RestaurantOutPaginated(BaseModel):
    items: list[RestaurantOut]
    total: int
    page: int
    size: int
    pages: int


class RestaurantEditOut(BaseModel):
    id: int
    restaurant_id: int
    user_id: Optional[int] = None
    suggestion_id: Optional[int] = None
    before: dict
    after: dict
    created_at: datetime

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%z"),
        }


class RestaurantFilters(BaseModel):
    """Filters for restaurants search."""
    name: Optional[str] = None
    name__ilike: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    vegan_status: Optional[RestaurantVeganStatus] = None
    operating_status: Optional[RestaurantOperatingStatus] = None
    has_storefront: Optional[bool] = None
    validated: Optional[bool] = None
    created_by: Optional[int] = None
