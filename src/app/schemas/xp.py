from typing import Optional
from datetime import datetime, timezone
from pydantic import BaseModel


class XPActionTypeOut(BaseModel):
    id: int
    key: str
    label: str
    base_xp: int
    is_active: bool

    class Config:
        from_attributes = True


class XPActionTypeUpdate(BaseModel):
    """Fields an admin can tune on an XP action without a deploy."""
    label: Optional[str] = None
    base_xp: Optional[int] = None
    is_active: Optional[bool] = None


class XPEventOut(BaseModel):
    id: int
    action_key: Optional[str] = None
    xp_awarded: int
    reference_type: Optional[str] = None
    reference_id: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%z"),
        }


class XPGrant(BaseModel):
    """One XP award, as surfaced inline on an action's create response.

    Actions that can award more than one tier at once (e.g. a scan is
    always a basic_scan, and can also be a vegandex_scan and/or a
    vegandex_scan_first_in_shop) return a list of these so clients can
    tell tiers apart instead of only seeing a combined total — e.g. to
    show a distinct "first to find this here!" toast.
    """
    action_key: str
    xp: int


class XPEventOutPaginated(BaseModel):
    items: list[XPEventOut]
    total: int
    page: int
    size: int
    pages: int
