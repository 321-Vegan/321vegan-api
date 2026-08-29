import enum
from datetime import datetime
from typing import Optional, cast
from sqlalchemy import Column, Integer, String, Text, Boolean, ForeignKey, Enum, DateTime, select, desc
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship
from app.database.base_class import Base
from app.models.checking import Checking
from app.models.brand import Brand
from app.models.user import User


class ProductState(str, enum.Enum):
    CREATED = "CREATED"
    NEED_CONTACT = "NEED_CONTACT"
    WAITING_REPLY = "WAITING_BRAND_REPLY"
    TO_INVESTIGATE = "TO_INVESTIGATE"
    WAITING_PUBLISH = "WAITING_PUBLISH"
    PUBLISHED = "PUBLISHED"


class ProductStatus(str, enum.Enum):
    VEGAN = "VEGAN"
    NON_VEGAN = "NON_VEGAN"
    MAYBE_VEGAN = "MAYBE_VEGAN"
    NOT_FOUND = "NOT_FOUND"


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    ean = Column(String, unique=True, index=True, nullable=False)
    name = Column(String)
    description = Column(Text)
    problem_description = Column(Text)
    image = Column(String, nullable=True)
    brand_id = Column(Integer, ForeignKey("brands.id"))
    brand = relationship("Brand", back_populates="products")
    status = Column(Enum(ProductStatus), default=ProductStatus.MAYBE_VEGAN)
    biodynamic = Column(Boolean, default=False)
    state = Column(Enum(ProductState), default=ProductState.CREATED)
    created_from_off = Column(Boolean, default=False)
    has_non_vegan_old_receipe = Column(Boolean, nullable=True)
    last_modified_by = Column(Integer, ForeignKey(
        "users.id"), nullable=True)
    interesting_product_id = Column(Integer, ForeignKey(
        "interesting_products.id", ondelete="SET NULL"), nullable=True)
    interesting_product = relationship(
        "InterestingProduct", back_populates="alternative_products")
    checkings = relationship("Checking",
                             back_populates="product",
                             cascade="all, delete",
                             passive_deletes=True,
                             lazy="selectin",
                             order_by=lambda: desc(Checking.requested_on))

    @hybrid_property
    def brand_name(self):
        if self.brand:
            return self.brand.name
        else:
            return None

    @brand_name.inplace.expression
    @classmethod
    def _brand_name_expression(cls):
        return (
            select(Brand.name)
            .where(Brand.id == cls.brand_id)
            .as_scalar()
        )

    @hybrid_property
    def last_requested_on(self):
        if self.checkings:
            return max(
                self.checkings,
                key=lambda checking: checking.requested_on
            ).requested_on
        else:
            return None

    @last_requested_on.inplace.expression
    @classmethod
    def _last_requested_on_expression(cls):
        return (
            select(Checking.requested_on)
            .where(Checking.product_id == cls.id)
            .order_by(Checking.requested_on.desc())
            .limit(1)
            .as_scalar()
        )

    @hybrid_property
    def last_requested_by(self):
        if self.checkings:
            return max(
                self.checkings,
                key=lambda checking: checking.requested_on
            ).user.nickname
        else:
            return None

    @last_requested_by.inplace.expression
    @classmethod
    def _last_requested_by_expression(cls):
        return (
            select(User.nickname)
            .where(Checking.product_id == cls.id)
            .join(Checking.user)
            .order_by(Checking.requested_on.desc())
            .limit(1)
            .as_scalar()
        )
