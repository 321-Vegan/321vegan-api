from pydantic import BaseModel, Field, field_validator, HttpUrl
from fastapi import Query
from typing import List, Optional, TYPE_CHECKING
from datetime import datetime, timezone

if TYPE_CHECKING:
    from app.schemas.partner_category import PartnerCategoryOut


class PartnerBase(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    logo_path: Optional[str] = None
    description: Optional[str] = None
    discount_text: Optional[str] = None
    discount_code: Optional[str] = None
    is_affiliate: Optional[bool] = False
    show_code_in_website: Optional[bool] = False
    is_active: Optional[bool] = True
    display_order: Optional[int] = None
    category_id: Optional[int] = None


class PartnerCreate(PartnerBase):
    name: str
    url: str

    @field_validator('is_affiliate', 'show_code_in_website', mode='before')
    @classmethod
    def set_boolean_defaults(cls, v):
        return False if v is None else v

    @field_validator('is_active', mode='before')
    @classmethod
    def set_is_active_default(cls, v):
        return True if v is None else v


class PartnerUpdate(PartnerBase):
    pass


class PartnerInDB(PartnerBase):
    id: int
    created_at: datetime
    updated_at: datetime


class PartnerOut(BaseModel):
    id: int
    created_at: datetime
    updated_at: datetime
    name: str
    url: str
    logo_path: Optional[str] = None
    description: Optional[str] = None
    discount_text: Optional[str] = None
    discount_code: Optional[str] = None
    is_affiliate: bool = False
    show_code_in_website: bool = False
    is_active: bool = True
    display_order: int = 0
    category_id: Optional[int] = None
    category: Optional['PartnerCategoryOut'] = None

    @field_validator('is_affiliate', 'show_code_in_website', mode='before')
    @classmethod
    def set_boolean_defaults(cls, v):
        return False if v is None else v

    @field_validator('is_active', mode='before')
    @classmethod
    def set_is_active_default(cls, v):
        return True if v is None else v

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%z"),
        }


class PartnerOutPaginated(BaseModel):
    items: List[PartnerOut]
    total: int
    page: int
    size: int
    pages: int


class PartnerFilters(BaseModel):
    name: Optional[str] = None
    name__ilike: Optional[str] = None
    name__contains: Optional[str] = None
    is_affiliate: Optional[bool] = None
    show_code_in_website: Optional[bool] = None
    is_active: Optional[bool] = None
    category_id: Optional[int] = None
    category___name__contains: Optional[str] = None
    category___name__lookalike: Optional[str] = None
    category___id: Optional[str] = None
