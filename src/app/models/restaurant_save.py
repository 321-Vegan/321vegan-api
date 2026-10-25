from datetime import datetime
from sqlalchemy import Column, Integer, DateTime, ForeignKey, UniqueConstraint
from app.database.base_class import Base


class RestaurantSave(Base):
    """A restaurant saved by a user, to find it again later."""
    __tablename__ = "restaurant_saves"
    __table_args__ = (
        UniqueConstraint("user_id", "restaurant_id",
                         name="uq_restaurant_save_user_restaurant"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey(
        "users.id", ondelete="CASCADE"), nullable=False, index=True)
    restaurant_id = Column(Integer, ForeignKey(
        "restaurants.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.now,
                        nullable=False, index=True)
