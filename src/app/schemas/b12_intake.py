from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime

from app.models.b12_intake import B12IntakeFrequency


class B12IntakeBase(BaseModel):
    intake_date: date
    user_id: int
    # Rhythm in effect when the intake was taken (daily, weekly,
    # twice_weekly, biweekly); needed to compare intakes fairly across
    # users with different dosage schemes.
    frequency: Optional[B12IntakeFrequency] = None


class B12IntakeCreate(B12IntakeBase):
    user_id: Optional[int] = None


class B12IntakeInDB(B12IntakeBase):
    id: int
    created_at: datetime


class B12IntakeOut(B12IntakeInDB):
    xp_awarded: Optional[int] = None

    class Config:
        from_attributes = True


class B12IntakeFilters(BaseModel):
    """Filters for B12 intakes search."""
    user_id: Optional[int] = None
