from datetime import date
from typing import Optional

from pydantic import BaseModel, Field

# The course's length: the app's VeganuaryService.totalDays
VEGANUARY_DAYS = 31


class VeganuaryDayIn(BaseModel):
    completed_on: date
    myth_id: Optional[str] = Field(default=None, max_length=64)


class VeganuaryDayOut(BaseModel):
    day: int
    completed_on: date
    myth_id: Optional[str] = None

    class Config:
        from_attributes = True
