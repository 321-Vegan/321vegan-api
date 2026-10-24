from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator
from app.models.restaurant_edit_suggestion import RestaurantEditSuggestionKind, RestaurantEditSuggestionStatus
from app.schemas.restaurant import RestaurantBase, RestaurantPhotoOut

# Field of `changes` listing the photos proposed for removal
REMOVE_PHOTO_IDS = "remove_photo_ids"


class RestaurantSuggestionCreate(BaseModel):
    restaurant_id: int
    kind: RestaurantEditSuggestionKind = RestaurantEditSuggestionKind.EDIT
    # Proposed values by restaurant field (EDIT only)
    changes: Dict[str, Any] = {}
    # Outdated place or menu photos to remove (EDIT only)
    remove_photo_ids: List[int] = []
    # The restaurant this one duplicates (DUPLICATE only)
    duplicate_of_id: Optional[int] = None
    comment: Optional[str] = Field(None, max_length=2000)

    @model_validator(mode="after")
    def check_kind(self):
        unknown = set(self.changes) - set(RestaurantBase.model_fields)
        if unknown:
            raise ValueError(
                f"These fields can't be changed: {', '.join(sorted(unknown))}")
        if self.kind == RestaurantEditSuggestionKind.EDIT:
            if not self.changes and not self.remove_photo_ids:
                raise ValueError("An edit needs changes or photos to remove")
        elif self.changes or self.remove_photo_ids:
            raise ValueError("Only an edit carries changes")
        if (self.kind == RestaurantEditSuggestionKind.DUPLICATE) != (self.duplicate_of_id is not None):
            raise ValueError(
                "duplicate_of_id is required for a duplicate, and only then")
        if self.duplicate_of_id is not None and self.duplicate_of_id == self.restaurant_id:
            raise ValueError("A restaurant can't duplicate itself")
        return self


class RestaurantSuggestionApply(BaseModel):
    """
    What the moderator applies from an edit: the chosen fields (all by
    default, `remove_photo_ids` included), with values possibly retouched.
    """
    fields: Optional[List[str]] = None
    values: Dict[str, Any] = {}


class RestaurantSuggestionReject(BaseModel):
    rejection_reason: Optional[str] = Field(None, max_length=500)


class RestaurantBriefOut(BaseModel):
    id: int
    name: str
    city: Optional[str] = None
    validated: bool

    class Config:
        from_attributes = True


class RestaurantSuggestionOut(BaseModel):
    id: int
    restaurant_id: int
    restaurant: RestaurantBriefOut
    user_id: Optional[int] = None
    user_nickname: Optional[str] = None
    kind: str
    duplicate_of_id: Optional[int] = None
    duplicate_of: Optional[RestaurantBriefOut] = None
    changes: Optional[Dict[str, Any]] = None
    # Values when the suggestion was made
    base_values: Optional[Dict[str, Any]] = None
    # Values now: different from base_values when the restaurant changed since
    current_values: Optional[Dict[str, Any]] = None
    # The photos proposed for removal that still exist
    photos_to_remove: List[RestaurantPhotoOut] = []
    comment: Optional[str] = None
    status: str
    applied_changes: Optional[Dict[str, Any]] = None
    reviewed_by: Optional[int] = None
    reviewed_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%z"),
        }


class RestaurantSuggestionOutPaginated(BaseModel):
    items: list[RestaurantSuggestionOut]
    total: int
    page: int
    size: int
    pages: int


class RestaurantSuggestionOutCount(BaseModel):
    total: int


class RestaurantSuggestionFilters(BaseModel):
    """Filters for restaurant suggestions search."""
    restaurant_id: Optional[int] = None
    restaurant___name__contains: Optional[str] = None
    user_id: Optional[int] = None
    kind: Optional[RestaurantEditSuggestionKind] = None
    status: Optional[RestaurantEditSuggestionStatus] = None
    status__ne: Optional[RestaurantEditSuggestionStatus] = None
