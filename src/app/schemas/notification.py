from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class NotificationOut(BaseModel):
    id: int
    type: str
    title: str
    body: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    # Compatibility only: opened notifications are deleted, never stored as read.
    read_at: None = None
    expires_at: datetime

    class Config:
        from_attributes = True
