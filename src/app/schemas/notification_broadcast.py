from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NotificationBroadcastIn(BaseModel):
    # "  " is refused like ""
    model_config = ConfigDict(str_strip_whitespace=True)

    # What fits a push banner without being cut too much
    title: str = Field(min_length=1, max_length=100)
    body: str = Field(min_length=1, max_length=500)


class NotificationBroadcastOut(BaseModel):
    id: int
    title: str
    body: str
    recipient_count: int
    sent_by: str | None = None
    created_at: datetime
    # Zero once the notifications are past their retention period
    read_count: int = 0
    pushes_sent: int = 0
    pushes_failed: int = 0
    pushes_pending: int = 0


class NotificationBroadcastRecipientsOut(BaseModel):
    count: int
