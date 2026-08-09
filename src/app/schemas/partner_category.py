from app.schemas.partner import PartnerOut
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timezone


class PartnerCategoryBase(BaseModel):
    name: Optional[str] = None
    display_order: Optional[int] = None


class PartnerCategoryCreate(PartnerCategoryBase):
    name: str


class PartnerCategoryUpdate(PartnerCategoryBase):
    pass


class PartnerCategoryInDB(PartnerCategoryBase):
    id: int
    created_at: datetime
    updated_at: datetime


class PartnerCategoryOut(BaseModel):
    id: int
    created_at: datetime
    updated_at: datetime
    name: str
    display_order: int = 0

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%z"),
        }


class PartnerCategoryOutPaginated(BaseModel):
    items: List[PartnerCategoryOut]
    total: int
    page: int
    size: int
    pages: int


class PartnerCategoryFilters(BaseModel):
    name: Optional[str] = None
    name__ilike: Optional[str] = None
    name__contains: Optional[str] = None
    name__lookalike: Optional[str] = None


# Resolve forward references
PartnerOut.model_rebuild()
