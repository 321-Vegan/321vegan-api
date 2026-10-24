import enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Enum, ForeignKey, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.database.base_class import Base


class RestaurantEditSuggestionKind(str, enum.Enum):
    EDIT = "EDIT"
    # The place no longer has any vegan option: delist it
    NO_VEGAN_OPTION = "NO_VEGAN_OPTION"
    # The place already exists as duplicate_of_id
    DUPLICATE = "DUPLICATE"


class RestaurantEditSuggestionStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED"
    REJECTED = "REJECTED"


class RestaurantEditSuggestion(Base):
    """
    Change of a validated restaurant proposed by a user, applied in full or
    in part by a moderator.
    """
    __tablename__ = "restaurant_edit_suggestions"
    __table_args__ = (
        # One pending suggestion per user and restaurant
        Index("uq_restaurant_edit_suggestion_pending",
              "restaurant_id", "user_id",
              unique=True,
              postgresql_where=text("status = 'PENDING'")),
    )

    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    user_id = Column(Integer, ForeignKey(
        "users.id", ondelete="SET NULL"), nullable=True, index=True)
    kind = Column(Enum(RestaurantEditSuggestionKind), nullable=False,
                  default=RestaurantEditSuggestionKind.EDIT)
    duplicate_of_id = Column(Integer, ForeignKey(
        "restaurants.id", ondelete="SET NULL"), nullable=True)
    # Only the changed fields
    changes = Column(JSONB, nullable=True)
    # Values of those fields when the suggestion was made, to spot conflicts
    base_values = Column(JSONB, nullable=True)
    comment = Column(Text, nullable=True)
    status = Column(Enum(RestaurantEditSuggestionStatus), nullable=False,
                    default=RestaurantEditSuggestionStatus.PENDING, index=True)
    # What the moderator actually applied
    applied_changes = Column(JSONB, nullable=True)
    reviewed_by = Column(Integer, ForeignKey(
        "users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    rejection_reason = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.now,
                        nullable=False, index=True)

    restaurant = relationship("Restaurant", foreign_keys=[restaurant_id])
    duplicate_of = relationship("Restaurant", foreign_keys=[duplicate_of_id])
    user = relationship("User", foreign_keys=[user_id])
    reviewer = relationship("User", foreign_keys=[reviewed_by])
