from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, EmailStr, Field, field_validator
from app.schemas.restaurant import RestaurantMapOut, RestaurantPhotoOut

MAX_SELECTION_RESTAURANTS = 50
MAX_TITLE_LENGTH = 100
MAX_DESCRIPTION_LENGTH = 1000
MAX_NOTE_LENGTH = 500


class RestaurantSelectionItemIn(BaseModel):
    restaurant_id: int
    # Why it is recommended
    note: Optional[str] = Field(None, max_length=MAX_NOTE_LENGTH)

    @field_validator("note", mode="before")
    @classmethod
    def strip_note(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value


class RestaurantSelectionFields(BaseModel):
    """Checks shared by the creation and the update."""

    @field_validator("title", mode="before", check_fields=False)
    @classmethod
    def strip_title(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("description", mode="before", check_fields=False)
    @classmethod
    def strip_description(cls, value):
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("items", check_fields=False)
    @classmethod
    def check_items(cls, items):
        if items is not None:
            ids = [item.restaurant_id for item in items]
            if len(ids) != len(set(ids)):
                raise ValueError(
                    "A restaurant can only be once in a selection")
        return items


class RestaurantSelectionCreate(RestaurantSelectionFields):
    title: str = Field(..., min_length=1, max_length=MAX_TITLE_LENGTH)
    description: Optional[str] = Field(
        None, max_length=MAX_DESCRIPTION_LENGTH)
    # In the order of the selection
    items: List[RestaurantSelectionItemIn] = Field(
        [], max_length=MAX_SELECTION_RESTAURANTS)


class RestaurantSelectionUpdate(RestaurantSelectionFields):
    """Partial update; items, when given, replace the whole list (order included)."""
    title: Optional[str] = Field(
        None, min_length=1, max_length=MAX_TITLE_LENGTH)
    description: Optional[str] = Field(
        None, max_length=MAX_DESCRIPTION_LENGTH)
    items: Optional[List[RestaurantSelectionItemIn]] = Field(
        None, max_length=MAX_SELECTION_RESTAURANTS)


class RestaurantSelectionSend(BaseModel):
    email: EmailStr


class RestaurantSelectionSummaryOut(BaseModel):
    """A selection in a list, as seen by its owner or by a recipient."""
    id: int
    title: str
    description: Optional[str] = None
    owner_nickname: str
    is_owner: bool
    # The restaurants the viewer can see, in order
    restaurant_ids: List[int] = []
    # Featured photos of the first restaurants having one (up to 4)
    cover_photos: List[RestaurantPhotoOut] = []
    # Recipient only: PENDING or ACCEPTED
    share_status: Optional[str] = None
    # Recipient only: false until they opened their received selections
    is_seen: bool = True
    # Recipient only: when it was sent to them
    shared_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        json_encoders = {
            datetime: lambda v: v.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%z"),
        }


class RestaurantSelectionItemOut(BaseModel):
    restaurant: RestaurantMapOut
    note: Optional[str] = None


class RestaurantSelectionOut(RestaurantSelectionSummaryOut):
    items: List[RestaurantSelectionItemOut] = []


class RestaurantSelectionSummaryOutPaginated(BaseModel):
    items: List[RestaurantSelectionSummaryOut]
    total: int
    page: int
    size: int
    pages: int


class RestaurantSelectionUnreadCountOut(BaseModel):
    count: int
