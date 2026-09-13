from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, ForeignKey, desc
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property
from app.database.base_class import Base
from app.models.shop_review import ShopReview
from app.models.scan_event import ScanEvent
from app.models.product_not_found_report import ProductNotFoundReport
from app.models.product_found_report import ProductFoundReport


class Shop(Base):
    """
    Shop model representing a physical store location.
    """
    __tablename__ = "shops"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    latitude = Column(Float, nullable=False, index=True)
    longitude = Column(Float, nullable=False, index=True)
    address = Column(String, nullable=True)
    city = Column(String, nullable=True)
    country = Column(String, nullable=True)
    osm_id = Column(String, nullable=True, unique=True, index=True)
    # node or way (relation not searched)
    osm_type = Column(String, nullable=True)
    shop_type = Column(String, nullable=True)  # supermarket, convenience, ...
    # null = created automatically (e.g. via Overpass API), set = manually created by a user
    created_by = Column(Integer, ForeignKey(
        "users.id", ondelete="SET NULL"), nullable=True, index=True)
    user = relationship("User", back_populates="shops")
    # False for shops manually created by a user, pending admin validation.
    # Shops created automatically (e.g. via Overpass API) are validated by default.
    validated = Column(Boolean, default=True,
                       server_default='true', nullable=False, index=True)
    created_at = Column(DateTime(timezone=True),
                        server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(
    ), onupdate=func.now(), nullable=False)
    date_deleted = Column(DateTime(timezone=True), nullable=True, index=True)
    reviews = relationship("ShopReview",
                           back_populates="shop",
                           cascade="all, delete",
                           passive_deletes=True,
                           lazy="selectin",
                           order_by=lambda: desc(ShopReview.created_at))
    scan_events = relationship("ScanEvent",
                               back_populates="shop",
                               cascade="all, delete",
                               passive_deletes=True,
                               lazy="selectin",
                               order_by=lambda: desc(ScanEvent.created_at))
    not_found_reports = relationship("ProductNotFoundReport",
                                     back_populates="shop",
                                     cascade="all, delete",
                                     passive_deletes=True,
                                     lazy="selectin",
                                     order_by=lambda: desc(ProductNotFoundReport.created_at))
    found_reports = relationship("ProductFoundReport",
                                 back_populates="shop",
                                 cascade="all, delete",
                                 passive_deletes=True,
                                 lazy="selectin",
                                 order_by=lambda: desc(ProductFoundReport.created_at))

    @hybrid_property
    def last_scanned_at(self):
        if self.scan_events:
            return max(
                self.scan_events,
                key=lambda scan_event: scan_event.created_at
            ).created_at
        else:
            return None

    @last_scanned_at.inplace.expression
    @classmethod
    def _last_scanned_at_expression(cls):
        return (
            select(ScanEvent.created_at)
            .where(ScanEvent.shop_id == cls.id)
            .order_by(ScanEvent.created_at.desc())
            .limit(1)
            .as_scalar()
        )
