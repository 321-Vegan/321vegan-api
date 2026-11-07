from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime, timezone
from app.schemas.product import Product

class ErrorReportBase(BaseModel):
    ean: str = Field(..., min_length=1)
    comment: str = Field(..., min_length=1)
    contact: Optional[str] = None


class ErrorReportCreate(ErrorReportBase):
    # Old app versions send the author in the body with the API key only.
    # Ignored when the caller is an authenticated user.
    created_by: Optional[int] = None


class ErrorReportUpdate(BaseModel):
    comment: Optional[str] = Field(None, min_length=1)
    contact: Optional[str] = None
    handled: Optional[bool] = None
    response: Optional[str] = None


class ErrorReportInDB(ErrorReportBase):
    id: int
    created_at: datetime
    updated_at: datetime
    handled: bool = False
    created_by: Optional[int] = None


class ErrorReportOut(BaseModel):
    id: int
    created_at: datetime
    updated_at: datetime
    ean: str
    comment: str
    contact: Optional[str] = None
    handled: bool
    response: Optional[str] = None
    created_by: Optional[int] = None
    product: Optional[Product] = None

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%z"),
        }


class ErrorReportOutPaginated(BaseModel):
    items: List[ErrorReportOut]
    total: int
    page: int
    size: int
    pages: int


class ErrorReportOutCount(BaseModel):
    total: int


class ErrorReportFilters(BaseModel):
    ean: Optional[str] = None
    ean__ilike: Optional[str] = None
    ean__contains: Optional[str] = None
    comment__contains: Optional[str] = None
    contact: Optional[str] = None
    contact__contains: Optional[str] = None
    handled: Optional[bool] = None
    created_at: Optional[str] = None
    created_at__gt: Optional[str] = None
