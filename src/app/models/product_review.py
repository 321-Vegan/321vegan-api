import enum
from typing import Optional
from sqlalchemy import Column, Integer, ForeignKey, DateTime, Text, Enum, CheckConstraint, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property
from datetime import datetime
from app.database.base_class import Base


class ProductReviewStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ProductReview(Base):
    __tablename__ = "product_reviews"
    __table_args__ = (
        CheckConstraint("rating >= 0 AND rating <= 5",
                        name="ck_product_review_rating"),
        UniqueConstraint("product_id", "user_id",
                         name="uq_product_review_product_user"),
    )

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    user_id = Column(Integer, ForeignKey(
        "users.id", ondelete="SET NULL"), nullable=True, index=True)
    rating = Column(Integer, nullable=False)
    comment = Column(Text, nullable=True)
    status = Column(Enum(ProductReviewStatus), nullable=False,
                    default=ProductReviewStatus.PENDING, index=True)
    created_at = Column(DateTime, default=datetime.now,
                        nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.now,
                        onupdate=datetime.now, nullable=False)

    # Relationships
    user = relationship("User", back_populates="product_reviews")
    product = relationship("Product", back_populates="reviews")

    @hybrid_property
    def user_nickname(self) -> Optional[str]:
        return self.user.nickname if self.user else None

    @property
    def user_is_premium(self) -> bool:
        return self.user.is_premium if self.user else False
