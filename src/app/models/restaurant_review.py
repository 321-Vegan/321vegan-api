import enum
from typing import Optional
from sqlalchemy import Column, Integer, ForeignKey, DateTime, Text, Enum, CheckConstraint, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property
from datetime import datetime
from app.database.base_class import Base


class RestaurantReviewStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RestaurantReview(Base):
    """
    Review of a restaurant: an overall rating (`rating`, the one shown on the
    map) and optional detailed ratings, all from 1 to 5.
    """
    __tablename__ = "restaurant_reviews"
    __table_args__ = (
        CheckConstraint("rating >= 1 AND rating <= 5",
                        name="ck_restaurant_review_rating"),
        CheckConstraint("rating_choice >= 1 AND rating_choice <= 5",
                        name="ck_restaurant_review_rating_choice"),
        CheckConstraint("rating_value >= 1 AND rating_value <= 5",
                        name="ck_restaurant_review_rating_value"),
        CheckConstraint("rating_taste >= 1 AND rating_taste <= 5",
                        name="ck_restaurant_review_rating_taste"),
        CheckConstraint("rating_service >= 1 AND rating_service <= 5",
                        name="ck_restaurant_review_rating_service"),
        UniqueConstraint("restaurant_id", "user_id",
                         name="uq_restaurant_review_restaurant_user"),
    )

    id = Column(Integer, primary_key=True, index=True)
    restaurant_id = Column(Integer, ForeignKey("restaurants.id", ondelete="CASCADE"),
                           nullable=False, index=True)
    user_id = Column(Integer, ForeignKey(
        "users.id", ondelete="SET NULL"), nullable=True, index=True)
    # Overall experience
    rating = Column(Integer, nullable=False)
    # Vegan choice
    rating_choice = Column(Integer, nullable=True)
    # Value for money
    rating_value = Column(Integer, nullable=True)
    # Taste / quality
    rating_taste = Column(Integer, nullable=True)
    # Welcome / service
    rating_service = Column(Integer, nullable=True)
    comment = Column(Text, nullable=True)
    status = Column(Enum(RestaurantReviewStatus), nullable=False,
                    default=RestaurantReviewStatus.PENDING, index=True)
    created_at = Column(DateTime, default=datetime.now,
                        nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.now,
                        onupdate=datetime.now, nullable=False)

    user = relationship("User", back_populates="restaurant_reviews")
    restaurant = relationship("Restaurant", back_populates="reviews")
    photos = relationship("RestaurantPhoto",
                          back_populates="review",
                          cascade="all, delete",
                          passive_deletes=True,
                          lazy="selectin")

    @hybrid_property
    def user_nickname(self) -> Optional[str]:
        return self.user.nickname if self.user else None

    @property
    def user_is_premium(self) -> bool:
        return self.user.is_premium if self.user else False
