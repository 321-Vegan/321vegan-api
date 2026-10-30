from datetime import date, datetime, timezone
from typing import List, NamedTuple, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.models.restaurant import RestaurantVeganStatus, RestaurantOperatingStatus, RestaurantTag, RestaurantServiceOption
from app.models.restaurant_photo import RestaurantPhotoKind, RestaurantPhotoStatus

TIME_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"
MINUTES_PER_DAY = 24 * 60
MINUTES_PER_WEEK = 7 * MINUTES_PER_DAY
MAX_PLANT_MILK_SURCHARGE = 5
MAX_STOPS = 14
CONTACT_FIELDS = ("phone", "website", "facebook", "instagram")
TEXT_FIELDS = ("name", "address", "city", "country", "description",
               "vegan_options_details", "service_area", "opening_hours_note",
               "phone", "website", "facebook", "instagram", "menu_url",
               "closure_note")


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


class RestaurantStop(BaseModel):
    """
    A place a food truck goes back to every week. Empty opening_hours = its
    days there vary, told in its note ("un samedi sur deux").
    """
    label: Optional[str] = Field(None, max_length=100)
    address: Optional[str] = None
    city: Optional[str] = None
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    opening_hours: List[OpeningSlot] = []
    note: Optional[str] = Field(None, max_length=200)

    @field_validator("label", "address", "city", "note", mode="before")
    @classmethod
    def strip_text(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


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
    # At least one vegan option is also gluten free
    has_gluten_free_options: bool = False
    tags: List[RestaurantTag] = Field(..., min_length=1)
    service_options: List[RestaurantServiceOption] = []
    plant_milk_surcharge: Optional[float] = Field(
        None, ge=-MAX_PLANT_MILK_SURCHARGE, le=MAX_PLANT_MILK_SURCHARGE)
    # False = no hot drinks (no surcharge to know), null = unknown
    serves_hot_drinks: Optional[bool] = None
    has_storefront: bool = True
    service_area: Optional[str] = Field(None, max_length=200)
    opening_hours: Optional[List[OpeningSlot]] = None
    opening_hours_note: Optional[str] = Field(None, max_length=500)
    # Food trucks only; the first stop is the restaurant's position
    stops: Optional[List[RestaurantStop]] = Field(None, max_length=MAX_STOPS)
    phone: Optional[str] = Field(None, max_length=50)
    website: Optional[str] = Field(None, max_length=500)
    facebook: Optional[str] = Field(None, max_length=500)
    instagram: Optional[str] = Field(None, max_length=500)
    menu_url: Optional[str] = Field(None, max_length=500)
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

    @field_validator("tags", "service_options")
    @classmethod
    def dedupe(cls, values):
        return list(dict.fromkeys(values))

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
        if self.vegan_status == RestaurantVeganStatus.FULLY_VEGAN:
            # No cow milk to compare with
            self.plant_milk_surcharge = None
        if self.plant_milk_surcharge is not None:
            if self.serves_hot_drinks is False:
                raise ValueError(
                    "A place without hot drinks has no plant milk surcharge")
            self.serves_hot_drinks = True

        if not self.has_storefront:
            if RestaurantServiceOption.DINE_IN in self.service_options:
                raise ValueError("A place without storefront can't be dine-in")
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

        if not self.stops:
            self.stops = None
        else:
            if RestaurantTag.FOOD_TRUCK not in self.tags:
                raise ValueError("Only a food truck can have stops")
            if not self.has_storefront:
                raise ValueError("A place without storefront can't have stops")
            # The map, the duplicates check and older apps only know the
            # restaurant's position and hours: keep them in sync. The truck
            # can't be at two stops at once, so their slots can't overlap.
            first = self.stops[0]
            self.latitude = first.latitude
            self.longitude = first.longitude
            self.address = first.address
            self.city = first.city or self.city
            slots = [slot for stop in self.stops for slot in stop.opening_hours]
            if slots:
                _check_no_overlap(slots)
            self.opening_hours = sorted(
                slots, key=lambda slot: slot.week_interval()) or None

        if self.operating_status != RestaurantOperatingStatus.TEMPORARILY_CLOSED:
            if self.closed_from or self.closed_until:
                raise ValueError(
                    "closed_from and closed_until are only for a temporary closure")
        elif self.closed_from and self.closed_until and self.closed_from > self.closed_until:
            raise ValueError("closed_from must be before closed_until")
        return self


class RestaurantCreate(RestaurantBase):
    pass


class RestaurantChange(NamedTuple):
    """A change of a restaurant, limited to the fields it really changes."""
    # New values to set on the restaurant, by field
    values: dict
    # JSON values of those fields, before and after
    before: dict
    after: dict


def restaurant_state(restaurant) -> dict:
    """Current values of a restaurant's RestaurantBase fields."""
    return {field: getattr(restaurant, field) for field in RestaurantBase.model_fields}


def compute_restaurant_change(restaurant, changes: dict) -> RestaurantChange:
    """
    Merge changes into a restaurant and check the business rules on the
    result. Fields set to their current value are left out.

    Raises:
        ValidationError: If the restaurant as it would be breaks a rule.
    """
    current = restaurant_state(restaurant)
    current_json = RestaurantBase.model_validate(current).model_dump(mode="json")
    new_state = RestaurantBase.model_validate({**current, **changes})
    new_json = new_state.model_dump(mode="json")
    new_values = new_state.model_dump()
    changed = [field for field in RestaurantBase.model_fields
               if new_json[field] != current_json[field]]
    return RestaurantChange(
        values={field: new_values[field] for field in changed},
        before={field: current_json[field] for field in changed},
        after={field: new_json[field] for field in changed},
    )


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
    has_gluten_free_options: Optional[bool] = None
    tags: Optional[List[RestaurantTag]] = None
    service_options: Optional[List[RestaurantServiceOption]] = None
    plant_milk_surcharge: Optional[float] = None
    serves_hot_drinks: Optional[bool] = None
    has_storefront: Optional[bool] = None
    service_area: Optional[str] = None
    opening_hours: Optional[List[OpeningSlot]] = None
    opening_hours_note: Optional[str] = None
    stops: Optional[List[RestaurantStop]] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    facebook: Optional[str] = None
    instagram: Optional[str] = None
    menu_url: Optional[str] = None
    operating_status: Optional[RestaurantOperatingStatus] = None
    closed_from: Optional[date] = None
    closed_until: Optional[date] = None
    closure_note: Optional[str] = None
    # Moderators only
    validated: Optional[bool] = None


class RestaurantDelete(BaseModel):
    # Why a pending restaurant is refused, shown to its creator
    rejection_reason: Optional[str] = Field(None, max_length=500)


class RestaurantPhotoOut(BaseModel):
    id: int
    restaurant_id: int
    review_id: Optional[int] = None
    kind: Optional[str] = None
    path: str
    status: str
    is_featured: bool = False
    user_id: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%z"),
        }


class RestaurantPhotoStatusUpdate(BaseModel):
    status: RestaurantPhotoStatus


class RestaurantPhotoKindUpdate(BaseModel):
    kind: RestaurantPhotoKind


class RestaurantLockOut(BaseModel):
    """The moderator holding the validation lock of a restaurant."""
    locked_by: str
    locked_at: datetime

    class Config:
        json_encoders = {
            datetime: lambda v: v.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%z"),
        }


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
    has_gluten_free_options: bool = False
    tags: List[str]
    service_options: List[str] = []
    plant_milk_surcharge: Optional[float] = None
    serves_hot_drinks: Optional[bool] = None
    has_storefront: bool
    service_area: Optional[str] = None
    opening_hours: Optional[List[OpeningSlot]] = None
    opening_hours_note: Optional[str] = None
    stops: Optional[List[RestaurantStop]] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    facebook: Optional[str] = None
    instagram: Optional[str] = None
    menu_url: Optional[str] = None
    operating_status: str
    closed_from: Optional[date] = None
    closed_until: Optional[date] = None
    closure_note: Optional[str] = None
    is_closed_now: bool
    osm_id: Optional[str] = None
    created_by: Optional[int] = None
    validated: bool
    # Refused by a moderator (only listed to its creator), with the reason
    is_rejected: bool = False
    rejection_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    # Approved photo shown first on the restaurant page
    featured_photo: Optional[RestaurantPhotoOut] = None
    photos: List[RestaurantPhotoOut] = []
    # Saved by the current user
    is_saved: bool = False

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
    # Shown under the name in the map search suggestions
    city: Optional[str] = None
    vegan_status: str
    has_gluten_free_options: bool = False
    tags: List[str]
    service_options: List[str] = []
    has_storefront: bool
    plant_milk_surcharge: Optional[float] = None
    serves_hot_drinks: Optional[bool] = None
    # For the "open now" filter of the map
    opening_hours: Optional[List[OpeningSlot]] = None
    # A pin per stop for food trucks
    stops: Optional[List[RestaurantStop]] = None
    operating_status: str
    is_closed_now: bool
    validated: bool
    rating_avg: Optional[float] = None
    review_count: int = 0
    # Shown right away when the restaurant page opens
    featured_photo: Optional[RestaurantPhotoOut] = None

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
    user_nickname: Optional[str] = None
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
    name__lookalike: Optional[str] = None
    city: Optional[str] = None
    city__lookalike: Optional[str] = None
    country: Optional[str] = None
    vegan_status: Optional[RestaurantVeganStatus] = None
    operating_status: Optional[RestaurantOperatingStatus] = None
    has_storefront: Optional[bool] = None
    validated: Optional[bool] = None
    created_by: Optional[int] = None
