from datetime import datetime
from typing import Optional
from sqlalchemy import Column, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from app.database.base_class import Base


class ProductEdit(Base):
    """
    History of a product: its creation (empty before) and every change made
    to it, from the backoffice or the app.
    """
    __tablename__ = "product_edits"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id", ondelete="CASCADE"),
                        nullable=False, index=True)
    # Author of the change, none for an API client
    user_id = Column(Integer, ForeignKey(
        "users.id", ondelete="SET NULL"), nullable=True, index=True)
    # Changed fields only
    before = Column(JSONB, nullable=False)
    after = Column(JSONB, nullable=False)
    created_at = Column(DateTime, default=datetime.now,
                        nullable=False, index=True)

    product = relationship("Product")
    user = relationship("User")

    @property
    def user_nickname(self) -> Optional[str]:
        return self.user.nickname if self.user else None
