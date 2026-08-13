from typing import Optional

from pydantic import BaseModel, EmailStr, field_validator


class Token(BaseModel):
    """Bearer Access Token"""

    access_token: str
    token_type: str


class TokenPayload(BaseModel):
    """Payload for Bearer Access Token"""

    sub: Optional[int] = None


class ApiKeyPayload(BaseModel):
    """Payload for Api Access Key"""

    api_key: Optional[str] = None


class PasswordResetRequest(BaseModel):
    """Schema for password reset request"""
    
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    """Schema for password reset confirmation"""
    
    token: str
    new_password: str


class PasswordResetTokenVerify(BaseModel):
    """Schema for password reset token verification"""
    
    token: str

class EmailChangeRequest(BaseModel):
    """Schema for requesting an email change"""

    new_email: EmailStr
    current_password: str


class PasswordChangeRequest(BaseModel):
    """Schema for changing the current user's password while logged in"""

    current_password: str
    new_password: str

