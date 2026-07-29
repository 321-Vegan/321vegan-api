from typing import List, Optional, TYPE_CHECKING
from pydantic import BaseModel, EmailStr, Field, field_validator
from datetime import datetime, timezone
from app.schemas.error_report import ErrorReportOut


class ScanSummaryItem(BaseModel):
    """Schema for scan summary item with EAN and scan count"""
    ean: str
    scan_count: int


class UserBase(BaseModel):
    role: str
    email: EmailStr
    nickname: str
    is_active: bool = False
    vegan_since: Optional[datetime] = None
    nb_products_sent: Optional[int] = 0
    nb_products_modified: Optional[int] = 0
    supporter: Optional[int] = 0

class UserCreate(UserBase):
    password: str

class UserUpdate(UserBase):
    pass

class UserInDB(UserBase):
    id: int
    created_at: datetime
    updated_at: datetime
    avatar: Optional[str] = None
    password: str

class UserOut(UserBase):
    id: int
    created_at: datetime
    updated_at: datetime
    avatar: Optional[str] = None
    roles: List
    nb_products_sent: int = 0
    nb_products_modified: int = 0
    nb_checkings: int = 0
    # Deprecated: kept for retrocompatibility, use nb_error_reports and
    # GET /error-reports/me instead
    error_reports: List['ErrorReportOut'] = []
    nb_error_reports: int = 0
    supporter: int = 0
    subscription_bypass: bool = False
    subscription_status: Optional[str] = None
    scan_count: int = 0
    scanned_products: List[ScanSummaryItem] = []
    xp: int = 0
    level: int = 1
    xp_to_next_level: int = 0
    login_streak_count: int = 0
    jetons: int = 0

    @field_validator('nb_products_sent', mode='before')
    @classmethod
    def validate_nb_products_sent(cls, v):
        """Convert None to 0 for nb_products_sent"""
        return 0 if v is None else v
    
    @field_validator('nb_products_modified', mode='before')
    @classmethod
    def validate_nb_products_modified(cls, v):
        """Convert None to 0 for nb_products_modified"""
        return 0 if v is None else v
    
    @field_validator('supporter', mode='before')
    @classmethod
    def validate_supporter(cls, v):
        """Convert None to 0 for supporter"""
        return 0 if v is None else v

    @field_validator('scan_count', mode='before')
    @classmethod
    def validate_scan_count(cls, v):
        """Convert None to 0 for scan_count"""
        return 0 if v is None else v

    class Config:
        from_attributes = True
        json_encoders = {
            datetime: lambda v: v.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%z"),
        }

class UserOutPaginated(BaseModel):
    items: List[UserOut]
    total: int
    page: int
    size: int
    pages: int

class UserFilters(BaseModel):
    nickname: Optional[str] = None
    nickname__ilike: Optional[str] = None
    nickname__contains: Optional[str] = None
    role: Optional[str] = None
    status: Optional[str] = None
    is_active: Optional[str] = None

class UserUpdateOwn(BaseModel):
    nickname: Optional[str] = None
    avatar: Optional[str] = None
    password: Optional[str] = None
    vegan_since: Optional[datetime] = None

class ScanCountIncrement(BaseModel):
    """Schema for incrementing the user's scan counter.

    `count` allows batching scans made offline into a single request.
    """
    count: int = Field(default=1, ge=1, le=10000)


class ScanCountInit(BaseModel):
    """Schema for seeding the user's scan counter from the app's local count."""
    count: int = Field(..., ge=0, le=1000000)


class ScanCountOut(BaseModel):
    scan_count: int
    xp_awarded: Optional[int] = None
    level: Optional[int] = None


class DailyCheckinOut(BaseModel):
    streak_count: int
    xp_awarded: int
    level: int


class UserPatch(BaseModel):
    """Schema for partial user updates (PATCH requests)"""
    role: Optional[str] = None
    email: Optional[EmailStr] = None
    nickname: Optional[str] = None
    is_active: Optional[bool] = None
    vegan_since: Optional[datetime] = None
    nb_products_sent: Optional[int] = None
    nb_products_modified: Optional[int] = None
    supporter: Optional[int] = None
    subscription_bypass: Optional[bool] = None
    password: Optional[str] = None


UserOut.model_rebuild()
