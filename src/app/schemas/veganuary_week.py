from datetime import date, datetime, timezone
from typing import Any, Dict, Optional

from pydantic import BaseModel


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%z")


class VeganuaryWeekIn(BaseModel):
    """The week's JSON, as the app reads it."""

    content: Dict[str, Any]


class VeganuaryWeekOut(BaseModel):
    number: int
    updated_at: datetime
    content: Dict[str, Any]

    class Config:
        from_attributes = True
        json_encoders = {datetime: _utc}


class VeganuaryImageOut(BaseModel):
    """An image of the course in the bucket: [path] is what the weeks' JSON
    refers to (the apps add the storage's address)."""

    path: str
    size: Optional[int] = None
    updated_at: Optional[datetime] = None

    class Config:
        json_encoders = {datetime: _utc}


class VeganuaryVersionOut(BaseModel):
    """[version] changes whenever a week is added, edited or removed: the
    app only downloads the weeks again when it differs from the one it has.
    Null while no week is stored. [opens_at]: the day the app's Veganuary
    tab opens (VEGANUARY_OPENS_AT in routes/veganuary_week.py)."""

    version: Optional[str] = None
    opens_at: Optional[date] = None
