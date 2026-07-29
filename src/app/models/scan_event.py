from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Float, Text, Index
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database.base_class import Base


class ScanEvent(Base):
    __tablename__ = "scan_events"
    __table_args__ = (
        # Backs ean_already_found_at_shop() (app.crud.scan_event), run on
        # every Vegandex scan for the "first to find this product in this
        # shop" XP bonus — declared here (not just via a raw op.create_index
        # in the migration) so autogenerate stops proposing to drop it.
        Index('ix_scan_events_ean_shop_id', 'ean', 'shop_id'),
    )

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    ean = Column(String, nullable=False, index=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    shop_id = Column(Integer, ForeignKey(
        "shops.id"), nullable=True, index=True)
    lookup_api_response = Column(Text, nullable=True)
    user_id = Column(Integer, ForeignKey(
        "users.id"), nullable=True)

    # Relationships
    user = relationship("User", back_populates="scan_events")
    shop = relationship("Shop", back_populates="scan_events")

    @property
    def shop_name(self) -> str:
        """Get shop name from relationship."""
        return self.shop.name if self.shop else None
