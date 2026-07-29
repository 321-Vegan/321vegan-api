from typing import Optional
from pydantic import BaseModel


class AvatarOut(BaseModel):
    id: int
    key: str
    label: str
    weight: int
    is_default: bool
    is_active: bool
    # Populated on GET /me/avatars (whether the current user can equip
    # this one); absent/None on the public catalog listing.
    owned: Optional[bool] = None

    class Config:
        from_attributes = True


class AvatarUpdate(BaseModel):
    """Fields an admin can tune on an avatar without a deploy."""
    label: Optional[str] = None
    weight: Optional[int] = None
    is_active: Optional[bool] = None


class AvatarPullOut(BaseModel):
    avatar: AvatarOut
    is_new: bool
    jetons_remaining: int
