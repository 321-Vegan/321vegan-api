import enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Enum, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from app.database.base_class import Base


class RestaurantSelectionShareStatus(str, enum.Enum):
    # Sent, not answered yet
    PENDING = "PENDING"
    # Shown with the recipient's saved restaurants
    ACCEPTED = "ACCEPTED"
    # Refused, or removed after accepting: kept so that sending the selection
    # again does nothing
    DECLINED = "DECLINED"


class RestaurantSelection(Base):
    """
    Restaurants a user recommends, in their order, with a title and a
    description. The user can send it to other users.
    """
    __tablename__ = "restaurant_selections"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey(
        "users.id", ondelete="CASCADE"), nullable=False, index=True)
    user = relationship("User")
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now,
                        onupdate=datetime.now, nullable=False)
    items = relationship("RestaurantSelectionItem",
                         back_populates="selection",
                         cascade="all, delete-orphan",
                         passive_deletes=True,
                         lazy="selectin",
                         order_by="RestaurantSelectionItem.position")


class RestaurantSelectionItem(Base):
    """A restaurant of a selection, with why it is recommended."""
    __tablename__ = "restaurant_selection_items"
    __table_args__ = (
        UniqueConstraint("selection_id", "restaurant_id",
                         name="uq_restaurant_selection_item"),
    )

    id = Column(Integer, primary_key=True, index=True)
    selection_id = Column(Integer, ForeignKey(
        "restaurant_selections.id", ondelete="CASCADE"), nullable=False, index=True)
    selection = relationship("RestaurantSelection", back_populates="items")
    restaurant_id = Column(Integer, ForeignKey(
        "restaurants.id", ondelete="CASCADE"), nullable=False, index=True)
    restaurant = relationship("Restaurant", lazy="selectin")
    # Order in the selection, from 0
    position = Column(Integer, nullable=False)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)


class RestaurantSelectionShare(Base):
    """A selection sent to a user, and their answer."""
    __tablename__ = "restaurant_selection_shares"
    __table_args__ = (
        UniqueConstraint("selection_id", "recipient_id",
                         name="uq_restaurant_selection_share"),
    )

    id = Column(Integer, primary_key=True, index=True)
    selection_id = Column(Integer, ForeignKey(
        "restaurant_selections.id", ondelete="CASCADE"), nullable=False, index=True)
    selection = relationship("RestaurantSelection")
    recipient_id = Column(Integer, ForeignKey(
        "users.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(Enum(RestaurantSelectionShareStatus), nullable=False,
                    default=RestaurantSelectionShareStatus.PENDING)
    # Set when the recipient opened their received selections
    seen_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now,
                        nullable=False, index=True)
    responded_at = Column(DateTime, nullable=True)
