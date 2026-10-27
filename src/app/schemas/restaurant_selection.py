from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
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
    # Listed for every user, for good
    is_public: bool = False


class RestaurantSelectionUpdate(RestaurantSelectionFields):
    """
    Partial update; items, when given, replace the whole list (order
    included). is_public can only go to true: a public selection stays so.
    """
    title: Optional[str] = Field(
        None, min_length=1, max_length=MAX_TITLE_LENGTH)
    description: Optional[str] = Field(
        None, max_length=MAX_DESCRIPTION_LENGTH)
    items: Optional[List[RestaurantSelectionItemIn]] = Field(
        None, max_length=MAX_SELECTION_RESTAURANTS)
    is_public: Optional[bool] = None


class RestaurantSelectionSend(BaseModel):
    """The recipient: by email, or by friend code."""
    email: Optional[EmailStr] = None
    friend_code: Optional[str] = Field(None, max_length=32)

    @model_validator(mode="after")
    def check_one_recipient(self):
        if (self.email is None) == (not self.friend_code):
            raise ValueError("Give either an email or a friend code")
        return self


class RestaurantSelectionSendOut(BaseModel):
    # Sent by friend code: who received it. Never told for an email, so it
    # doesn't tell who uses the app
    recipient_nickname: Optional[str] = None


class RestaurantSelectionSummaryOut(BaseModel):
    """
    A selection in a list, as seen by its owner, by a recipient, or by any
    user when public.
    """
    id: int
    title: str
    description: Optional[str] = None
    owner_id: int
    owner_nickname: str
    is_owner: bool
    is_public: bool = False
    # When it was made public
    published_at: Optional[datetime] = None
    # The restaurants the viewer can see, in order
    restaurant_ids: List[int] = []
    # Image chosen by the owner (bucket path), shown instead of cover_photos
    cover_path: Optional[str] = None
    # Featured photos of the first restaurants having one (up to 4)
    cover_photos: List[RestaurantPhotoOut] = []
    # Recipient, or user who took a public one: PENDING or ACCEPTED
    # (DECLINED when they removed a public one); null otherwise
    share_status: Optional[str] = None
    # Recipient only: false until they opened their received selections
    is_seen: bool = True
    # Recipient only: when it was sent to them
    shared_at: Optional[datetime] = None
    # Owner, or anyone for a public one: how many users accepted or took it
    # (have it with their saved restaurants)
    accepted_count: Optional[int] = None
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
