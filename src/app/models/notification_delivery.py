from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database.base_class import Base


class NotificationDelivery(Base):
    """The delivery state of one durable notification to one device."""

    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "notification_id",
            "device_id",
            name="uq_notification_deliveries_notification_device",
        ),
        Index(
            "ix_notification_deliveries_status_next_attempt",
            "status",
            "next_attempt_at",
            "id",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    notification_id = Column(
        Integer,
        ForeignKey("notifications.id", ondelete="CASCADE"),
        nullable=False,
    )
    device_id = Column(
        Integer,
        ForeignKey("push_devices.id", ondelete="CASCADE"),
        nullable=False,
    )
    status = Column(String(20), default="pending", nullable=False)
    attempt_count = Column(Integer, default=0, nullable=False)
    next_attempt_at = Column(DateTime, nullable=True)
    last_attempt_at = Column(DateTime, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    provider_message_id = Column(String(255), nullable=True)
    http_status = Column(Integer, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.now,
        onupdate=datetime.now,
        nullable=False,
    )

    notification = relationship("Notification", back_populates="deliveries")
    device = relationship("PushDevice", back_populates="deliveries")
