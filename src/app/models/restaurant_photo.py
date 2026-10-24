import enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Enum, ForeignKey
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
    user_id = Column(Integer, ForeignKey(
        "users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.now,
                        nullable=False, index=True)

    restaurant = relationship("Restaurant", back_populates="photos")
    review = relationship("RestaurantReview", back_populates="photos")
    user = relationship("User")
