import enum
from sqlalchemy import Column, Integer, Date, Enum, ForeignKey, DateTime, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database.base_class import Base


class B12IntakeFrequency(str, enum.Enum):
    """The user's supplementation rhythm when the intake was recorded.

    B12 dosage schemes differ (daily, weekly, twice weekly, biweekly,
    monthly), so a
    raw intake count is not comparable between users. Snapshotting the
    frequency on each intake lets consumers (e.g. the future XP system) apply
    per-frequency rules, such as the expected gap between intakes.
    """
    DAILY = "daily"
    WEEKLY = "weekly"
    TWICE_WEEKLY = "twice_weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"


class B12Intake(Base):
    __tablename__ = "b12_intakes"
    __table_args__ = (
        UniqueConstraint("user_id", "intake_date",
                         name="uq_b12_intake_user_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    intake_date = Column(Date, nullable=False, index=True)
    frequency = Column(Enum(B12IntakeFrequency), nullable=True)
    user_id = Column(Integer, ForeignKey(
        "users.id", ondelete="CASCADE"), nullable=False, index=True)

    # Relationships
    user = relationship("User", back_populates="b12_intakes")
