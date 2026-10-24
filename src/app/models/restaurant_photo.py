import enum
from datetime import datetime
from typing import Iterable, Optional
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Enum, ForeignKey, Index, text
from sqlalchemy.orm import relationship
from app.database.base_class import Base


class RestaurantPhotoKind(str, enum.Enum):
    PLACE = "PLACE"
    MENU = "MENU"


class RestaurantPhotoStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RestaurantPhoto(Base):
    """
    Photo of a restaurant (its place or its menu) or attached to a review.
    Stored in the S3 bucket under restaurants/{restaurant_id}/.
    """
    __tablename__ = "restaurant_photos"
    __table_args__ = (
        # At most one featured photo per restaurant
        Index("uq_restaurant_photo_featured", "restaurant_id",
              unique=True, postgresql_where=text("is_featured")),
    )

    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    # Set for a review photo, whose visibility follows the review status
    review_id = Column(Integer, ForeignKey("restaurant_reviews.id", ondelete="CASCADE"),
                       nullable=True, index=True)
    # Null for a review photo
    kind = Column(Enum(RestaurantPhotoKind), nullable=True, index=True)
    path = Column(String, nullable=False)
    status = Column(Enum(RestaurantPhotoStatus), nullable=False,
                    default=RestaurantPhotoStatus.PENDING, index=True)
    # Shown first on the restaurant page, chosen by a moderator (see
    # pick_featured_photo for the default)
    is_featured = Column(Boolean, default=False,
                         server_default="false", nullable=False)
    user_id = Column(Integer, ForeignKey(
        "users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.now,
                        nullable=False, index=True)

    restaurant = relationship("Restaurant", back_populates="photos")
    review = relationship("RestaurantReview", back_populates="photos")
    user = relationship("User")


def pick_featured_photo(photos: Iterable[RestaurantPhoto]) -> Optional[RestaurantPhoto]:
    """
    The photo shown first on a restaurant page, among its approved place and
    menu photos: the featured one, else the oldest place photo (the one sent
    with the restaurant, usually).
    """
    candidates = [
        photo for photo in photos
        if photo.review_id is None and photo.status == RestaurantPhotoStatus.APPROVED
    ]
    featured = next((p for p in candidates if p.is_featured), None)
    if featured:
        return featured
    places = [p for p in candidates if p.kind == RestaurantPhotoKind.PLACE]
    return min(places, key=lambda p: (p.created_at, p.id)) if places else None
