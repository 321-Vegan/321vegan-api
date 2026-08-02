import enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, Enum, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.database.base_class import Base


class SubscriptionPlatform(str, enum.Enum):
    APPLE = "apple"
    GOOGLE = "google"


class SubscriptionStatus(str, enum.Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    GRACE_PERIOD = "grace_period"
    PAUSED = "paused"


class SubscriptionEventType(str, enum.Enum):
    INITIAL_PURCHASE = "initial_purchase"
    RENEWAL = "renewal"
    CANCELLATION = "cancellation"
    EXPIRY = "expiry"
    REFUND = "refund"
    GRACE_PERIOD = "grace_period"
    PAUSED = "paused"


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    user_id = Column(Integer, ForeignKey("users.id"),
                     nullable=False, index=True)
    platform = Column(Enum(SubscriptionPlatform), nullable=False)
    original_transaction_id = Column(
        String, unique=True, nullable=False, index=True)
    transaction_id = Column(String, nullable=True)
    # Apple's notificationUUID of the last successfully processed webhook.
    # Used for idempotency instead of transaction_id: Apple reuses the same
    # transactionId across different notification types when no new
    # transaction occurred (e.g. EXPIRED reuses the prior DID_RENEW's
    # transactionId), so keying on transaction_id caused those follow-up
    # notifications to be misdetected as duplicates and skipped.
    last_notification_uuid = Column(String, nullable=True)
    purchase_token = Column(String, nullable=True)
    product_id = Column(String, nullable=False)
    status = Column(Enum(SubscriptionStatus),
                    default=SubscriptionStatus.ACTIVE, nullable=False)
    expires_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="subscriptions")
    events = relationship("SubscriptionEvent", back_populates="subscription",
                          cascade="all, delete", passive_deletes=True)


class SubscriptionEvent(Base):
    __tablename__ = "subscription_events"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.now)
    subscription_id = Column(Integer, ForeignKey(
        "subscriptions.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(Enum(SubscriptionEventType), nullable=False)
    platform_event_data = Column(Text, nullable=True)

    subscription = relationship("Subscription", back_populates="events")
