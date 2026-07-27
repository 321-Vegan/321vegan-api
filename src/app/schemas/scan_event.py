from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime, timezone
from app.schemas.xp import XPGrant


class NearbyShopOut(BaseModel):
    """A nearby shop returned alongside a scan event for shop selection.

    DB shops have an `id`. OSM-only shops have `osm_id` (and no `id`).
    Old app versions ignore entries without `id` and still work as before.
    """
    id: Optional[int] = None
    name: str
    address: Optional[str] = None
    city: Optional[str] = None
    osm_id: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    class Config:
        from_attributes = True


class ConfirmShopRequest(BaseModel):
    """Request body for confirming a shop from nearby_shops."""
    osm_id: str


class ScanEventBase(BaseModel):
    ean: str = Field(..., min_length=1)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    shop_id: Optional[int] = None
    lookup_api_response: Optional[str] = None
    user_id: Optional[int] = None


class ScanEventCreate(ScanEventBase):
    pass


class ScanEventUpdate(BaseModel):
    ean: Optional[str] = Field(None, min_length=1)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    shop_id: Optional[int] = None
    lookup_api_response: Optional[str] = None
    user_id: Optional[int] = None


class ScanEventInDB(ScanEventBase):
    id: int
    created_at: datetime


class ScanEventOut(ScanEventInDB):
    user_nickname: Optional[str] = None
    shop_name: Optional[str] = None
    nearby_shops: Optional[List[NearbyShopOut]] = None
    # Total across xp_grants, kept for clients that don't need the
    # breakdown. See xp_grants to tell "first find in this shop" (and
    # other tiers) apart from a plain scan.
    xp_awarded: Optional[int] = None
    xp_grants: List[XPGrant] = []

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%z"),
        }


class ScanEventOutPaginated(BaseModel):
    items: list[ScanEventOut]
    total: int
    page: int
    size: int
    pages: int


class ScanEventFilters(BaseModel):
    """Filters for scan events search."""
    ean: Optional[str] = None
    user_id: Optional[int] = None
    shop_id: Optional[int] = None
