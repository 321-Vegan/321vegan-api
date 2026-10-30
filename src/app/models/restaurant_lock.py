from datetime import datetime, timedelta
from sqlalchemy import Column, Integer, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.database.base_class import Base

RESTAURANT_LOCK_DURATION = timedelta(minutes=10)


class RestaurantLock(Base):
    """
    Validation lock of a restaurant: the moderator working on it, so that two
    of them don't validate it at the same time. It's renewed while they are
    on it, and ignored once older than RESTAURANT_LOCK_DURATION.
    """
    __tablename__ = "restaurant_locks"

    restaurant_id = Column(Integer, ForeignKey("restaurants.id", ondelete="CASCADE"),
                           primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                     nullable=False)
    locked_at = Column(DateTime, default=datetime.now, nullable=False)

    user = relationship("User")

    @property
    def is_expired(self) -> bool:
        return self.locked_at < datetime.now() - RESTAURANT_LOCK_DURATION
