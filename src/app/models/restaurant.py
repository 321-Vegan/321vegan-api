import enum
from datetime import date
from typing import Optional
from sqlalchemy import Column, Integer, String, Float, Boolean, Date, DateTime, Numeric, Text, Enum, ForeignKey, Index, desc
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database.base_class import Base
from app.models.restaurant_photo import RestaurantPhoto, pick_featured_photo
from app.models.restaurant_review import RestaurantReview


class RestaurantVeganStatus(str, enum.Enum):
    FULLY_VEGAN = "FULLY_VEGAN"
    # Not fully vegan, but with at least one clearly identified vegan option
    VEGAN_OPTIONS = "VEGAN_OPTIONS"


class RestaurantOperatingStatus(str, enum.Enum):
    OPEN = "OPEN"
    TEMPORARILY_CLOSED = "TEMPORARILY_CLOSED"
    PERMANENTLY_CLOSED = "PERMANENTLY_CLOSED"


class RestaurantTag(str, enum.Enum):
    RESTAURANT = "restaurant"
    CAFE = "cafe"
    BAKERY = "bakery"
    FOOD_TRUCK = "food_truck"
    FAST_FOOD = "fast_food"
    ICE_CREAM = "ice_cream"
    BAR = "bar"
    CATERER = "caterer"
    GROCERY = "grocery"
    HOTEL = "hotel"
    GUESTHOUSE = "guesthouse"
    HOSTEL = "hostel"


class RestaurantServiceOption(str, enum.Enum):
    DINE_IN = "dine_in"
    TAKEAWAY = "takeaway"
    DELIVERY = "delivery"


class Restaurant(Base):
    """
    Restaurant model: any place serving food that is fully vegan or has at
    least one clearly identified vegan option (restaurants, cafés, caterers,
    hotels...). The kind of place is carried by `tags`.
    """
    __tablename__ = "restaurants"
    __table_args__ = (
        Index("ix_restaurants_tags", "tags", postgresql_using="gin"),
    )

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    latitude = Column(Float, nullable=False, index=True)
    longitude = Column(Float, nullable=False, index=True)
    address = Column(String, nullable=True)
    city = Column(String, nullable=True)
    country = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    vegan_status = Column(Enum(RestaurantVeganStatus),
                          nullable=False, index=True)
    # Required when vegan_status is VEGAN_OPTIONS
    vegan_options_details = Column(Text, nullable=True)
    tags = Column(ARRAY(String), nullable=False, server_default="{}")
    # How to eat there (dine in, takeaway, delivery); empty = unknown
    service_options = Column(ARRAY(String), nullable=False,
                             server_default="{}")
    # Extra cost of plant milk in euros: 0 = no surcharge, < 0 = cow milk
    # costs more, null = unknown
    plant_milk_surcharge = Column(Numeric(5, 2), nullable=True)
    # False = no hot drinks, so no plant milk surcharge to know; null = unknown
    serves_hot_drinks = Column(Boolean, nullable=True)
    # False only for caterers without a place to visit (delivery, events)
    has_storefront = Column(Boolean, default=True,
                            server_default="true", nullable=False)
    service_area = Column(String, nullable=True)
    # [{"day": 0-6 (monday first), "open": "HH:MM", "close": "HH:MM"}, ...]
    # close < open means the slot ends after midnight
    opening_hours = Column(JSONB, nullable=True)
    opening_hours_note = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    website = Column(String, nullable=True)
    facebook = Column(String, nullable=True)
    instagram = Column(String, nullable=True)
    # Online menu (web page or PDF), when the place has one
    menu_url = Column(String, nullable=True)
    operating_status = Column(Enum(RestaurantOperatingStatus), nullable=False,
                              default=RestaurantOperatingStatus.OPEN,
                              server_default=RestaurantOperatingStatus.OPEN.value,
                              index=True)
    # Optional bounds of a temporary closure (an empty bound is open-ended)
    closed_from = Column(Date, nullable=True)
    closed_until = Column(Date, nullable=True)
    closure_note = Column(String, nullable=True)
    osm_id = Column(String, nullable=True, unique=True, index=True)
    osm_type = Column(String, nullable=True)
    # null = created automatically (e.g. OSM import), set = created by a user
    created_by = Column(Integer, ForeignKey(
        "users.id", ondelete="SET NULL"), nullable=True, index=True)
    user = relationship("User", back_populates="restaurants")
    # False for restaurants created by a user, pending moderation
    validated = Column(Boolean, default=True,
                       server_default="true", nullable=False, index=True)
    created_at = Column(DateTime(timezone=True),
                        server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(
    ), onupdate=func.now(), nullable=False)
    date_deleted = Column(DateTime(timezone=True), nullable=True, index=True)
    photos = relationship("RestaurantPhoto",
                          back_populates="restaurant",
                          cascade="all, delete",
                          passive_deletes=True,
                          lazy="selectin",
                          order_by=lambda: desc(RestaurantPhoto.created_at))
    reviews = relationship("RestaurantReview",
                           back_populates="restaurant",
                           cascade="all, delete",
                           passive_deletes=True,
                           order_by=lambda: desc(RestaurantReview.created_at))

    @property
    def featured_photo(self) -> Optional[RestaurantPhoto]:
        """The approved photo shown first on the restaurant page."""
        return pick_featured_photo(self.photos)

    @property
    def is_closed_now(self) -> bool:
        """Closed for good, or within the dates of a temporary closure."""
        if self.operating_status == RestaurantOperatingStatus.PERMANENTLY_CLOSED:
            return True
        if self.operating_status != RestaurantOperatingStatus.TEMPORARILY_CLOSED:
            return False
        today = date.today()
        if self.closed_from and today < self.closed_from:
            return False
        if self.closed_until and today > self.closed_until:
            return False
        return True
