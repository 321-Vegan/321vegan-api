from datetime import datetime
from typing import Optional
from sqlalchemy import Column, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.database.base_class import Base


class RestaurantEdit(Base):
    """
    History of the changes applied to a restaurant, whether made directly or
    through an accepted suggestion.
    """
    __tablename__ = "restaurant_edits"

    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    # Author of the change
    user_id = Column(Integer, ForeignKey(
        "users.id", ondelete="SET NULL"), nullable=True, index=True)
    suggestion_id = Column(Integer, ForeignKey(
        "restaurant_edit_suggestions.id", ondelete="SET NULL"), nullable=True)
    # Changed fields only
    before = Column(JSONB, nullable=False)
    after = Column(JSONB, nullable=False)
    created_at = Column(DateTime, default=datetime.now,
                        nullable=False, index=True)

    restaurant = relationship("Restaurant")
    user = relationship("User")
    suggestion = relationship("RestaurantEditSuggestion")

    @property
    def user_nickname(self) -> Optional[str]:
        return self.user.nickname if self.user else None
