from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database.base_class import Base


class PushDevice(Base):
    """An FCM destination registered by an authenticated user."""

    __tablename__ = "push_devices"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            name="uq_push_devices_installation_id",
        ),
        UniqueConstraint(
            "token",
            name="uq_push_devices_token",
        ),
        Index("ix_push_devices_user_enabled", "user_id", "enabled"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    platform = Column(String(20), nullable=False)
    installation_id = Column(String(255), nullable=True)
    token = Column(String(512), nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.now,
        onupdate=datetime.now,
        nullable=False,
    )
    last_seen_at = Column(DateTime, default=datetime.now, nullable=False)
    invalidated_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="push_devices")
    deliveries = relationship(
        "NotificationDelivery",
        back_populates="device",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
