from pydantic import BaseModel, Field
from fastapi import Query
from typing import List, Optional
from app.schemas.brand import Brand
from app.schemas.checking import CheckingOutForProduct
from datetime import datetime, timezone


class Product(BaseModel):
    id: int
    ean: str
    name: Optional[str] = None


class ProductBase(BaseModel):
    ean: str = Field(..., min_length=1)
    name: Optional[str] = None
    description: Optional[str] = None
    problem_description: Optional[str] = None
    brand_id: Optional[int] = None
    status: Optional[str] = None
    biodynamic: Optional[bool] = None
    state: Optional[str] = None
    has_non_vegan_old_receipe: Optional[bool] = None
    last_modified_by: Optional[int] = None
    image: Optional[str] = None
    interesting_product_id: Optional[int] = None


class ProductCreate(ProductBase):
    user_id: Optional[int] = None


class ProductUpdate(ProductBase):
    pass


class ProductFile(BaseModel):
    image: Optional[str] = None


class ProductInDB(ProductBase):
    id: int
    created_at: datetime
    updated_at: datetime
    created_from_off: bool


class ProductOut(BaseModel):
    id: int
    created_at: datetime
    updated_at: datetime
    ean: str
    name: Optional[str] = None
    description: Optional[str] = None
    problem_description: Optional[str] = None
    brand: Optional[Brand] = None
    status: str
    biodynamic: bool
    state: str
    created_from_off: bool
    checkings: List[CheckingOutForProduct]
    has_non_vegan_old_receipe: Optional[bool] = None
    last_requested_on: Optional[datetime] = None
    last_requested_by: Optional[str] = None
    image: Optional[str] = None
    xp_awarded: Optional[int] = None

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%z"),
        }


class ProductOutPaginated(BaseModel):
    items: List[ProductOut]
    total: int
    page: int
    size: int
    pages: int


class ProductOutCount(BaseModel):
    total: int


class ProductFilters(BaseModel):
    ean: Optional[str] = None
    ean__ne: Optional[str] = None
    name: Optional[str] = None
    name__ilike: Optional[str] = None
    name__contains: Optional[str] = None
    brand: Optional[str] = None
    brand___name__contains: Optional[str] = None
    brand___name__lookalike: Optional[str] = None
    brand___id: Optional[str] = None
    status: Optional[str] = None
    state: Optional[str] = None
    state__in: Optional[List[str]] = Field(Query(None))
    created_at: Optional[str] = None
    created_at__gt: Optional[str] = None
    updated_at__gt: Optional[str] = None
    last_requested_by__contains: Optional[str] = None
