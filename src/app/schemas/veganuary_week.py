from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pydantic import BaseModel


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%z")


class VeganuaryWeekIn(BaseModel):
    """The week's JSON, as in the app's `lib/assets/veganuary/weekN.json`."""

    content: Dict[str, Any]


class VeganuaryWeekOut(BaseModel):
    number: int
    updated_at: datetime
    content: Dict[str, Any]

    class Config:
        from_attributes = True
        json_encoders = {datetime: _utc}


class VeganuaryVersionOut(BaseModel):
    """Changes whenever a week is added, edited or removed: the app only
    downloads the weeks again when it differs from the one it has."""

    version: Optional[str] = None
