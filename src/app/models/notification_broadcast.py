from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database.base_class import Base


class NotificationBroadcast(Base):
    """A notification sent to every account with pushes turned on, from the
    admin tool: one Notification per account points back to it."""

    __tablename__ = "notification_broadcasts"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    body = Column(Text, nullable=False)
    # Kept here: the notifications themselves are deleted after their
    # retention period
    recipient_count = Column(Integer, nullable=False)
    sent_by_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, default=datetime.now, nullable=False)

    sent_by = relationship("User")
