from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database.base_class import Base


class PartnerCategory(Base):
    __tablename__ = "partner_categories"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    name = Column(String, nullable=False, unique=True, index=True)
    display_order = Column(Integer, nullable=False, default=0, server_default="0")

    # Relationship with partners
    partners = relationship("Partner", back_populates="category")
