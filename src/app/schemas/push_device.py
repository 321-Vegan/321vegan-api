from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class PushDeviceRegister(BaseModel):
    platform: Literal["android", "ios"]
    installation_id: str | None = None
    token: str

    @field_validator("installation_id")
    @classmethod
    def validate_installation_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        installation_id = value.strip()
        if not installation_id or len(installation_id) > 255:
            raise ValueError("Invalid Firebase installation ID")
        return installation_id

    @field_validator("token")
    @classmethod
    def validate_fcm_token(cls, value: str) -> str:
        token = value.strip()
        if not token or len(token) > 512 or any(char.isspace() for char in token):
            raise ValueError("Invalid FCM registration token")
        return token


class PushDeviceOut(BaseModel):
    id: int
    # Temporary response-only compatibility for clients built against the
    # pre-FCM-only contract. Neither value is persisted or used for routing.
    provider: Literal["fcm"] = Field(default="fcm", deprecated=True)
    environment: Literal["production"] = Field(
        default="production",
        deprecated=True,
    )
    platform: str
    installation_id: str | None
    enabled: bool
    created_at: datetime
    updated_at: datetime
    last_seen_at: datetime

    class Config:
        from_attributes = True
