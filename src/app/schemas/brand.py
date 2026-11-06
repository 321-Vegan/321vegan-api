from pydantic import BaseModel, Field, field_validator, EmailStr
from fastapi import Query
from typing import List, Optional
from datetime import datetime, timezone


class Brand(BaseModel):
    id: int
    name: str
    email: Optional[EmailStr] = None
    root_email: Optional[EmailStr] = None
    boycott: Optional[bool] = False
    background: Optional[str] = None

    @field_validator('boycott', mode='before')
    @classmethod
    def set_boycott_default(cls, v):
        return False if v is None else v


class BrandBase(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    contact_form_url: Optional[str] = None
    parent_id: Optional[int] = None
    logo_path: Optional[str] = None
    boycott: Optional[bool] = False
    background: Optional[str] = None


class BrandCreate(BrandBase):
    pass


class BrandUpdate(BrandBase):
    pass


class BrandInDB(BrandBase):
    id: int
    created_at: datetime
    updated_at: datetime


class BrandOut(BaseModel):
    id: int
    created_at: datetime
    updated_at: datetime
    name: str
    email: Optional[EmailStr] = None
    root_email: Optional[EmailStr] = None
    contact_form_url: Optional[str] = None
    logo_path: Optional[str] = None
    boycott: Optional[bool] = False
    parent: Optional[Brand] = None
    score: Optional[float] = None
    background: Optional[str] = None

    @field_validator('boycott', mode='before')
    @classmethod
    def set_boycott_default(cls, v):
        return False if v is None else v

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%z"),
        }


class BrandOutPaginated(BaseModel):
    items: List[BrandOut]
    total: int
    page: int
    size: int
    pages: int


class BrandFilters(BaseModel):
    name: Optional[str] = None
    name__ilike: Optional[str] = None
    name__contains: Optional[str] = None
    name__lookalike: Optional[str] = None
    name__in: Optional[List[str]] = Field(Query(None))
    name__iin: Optional[List[str]] = Field(Query(None))
    parent_id: Optional[int] = None
    parent___name__contains: Optional[str] = None
    parent___name__lookalike: Optional[str] = None
    boycott: Optional[bool] = None


class BrandLookalikeFilter(BaseModel):
    name: str = Field(Query(..., min_length=1))
