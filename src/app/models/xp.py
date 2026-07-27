from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property
from app.database.base_class import Base


class XPActionType(Base):
    """Catalog of actions that award XP, and how much each is worth.

    Kept as a DB table (rather than a Python enum) so XP values can be
    tuned, or new actions added, without a deploy. `key` is the stable
    identifier code refers to (see app.services.xp_service.XPAction).
    """
    __tablename__ = "xp_action_types"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    key = Column(String, unique=True, index=True, nullable=False)
    label = Column(String, nullable=False)
    base_xp = Column(Integer, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    events = relationship("XPEvent", back_populates="action_type")


class XPEvent(Base):
    """Append-only ledger of every XP grant.

    users.xp is a cached running total kept for fast reads; this table is
    the source of truth, an audit trail, and the basis for a future quest
    system (a quest is just N events of a given type within a period).

    reference_type/reference_id loosely point back at the row that
    triggered the grant (e.g. "scan_event"/123). No hard FK to those
    tables since the referenced entity varies by action and some of those
    rows can be deleted independently of the XP history.
    """
    __tablename__ = "xp_events"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.now,
                        nullable=False, index=True)
    user_id = Column(Integer, ForeignKey(
        "users.id", ondelete="CASCADE"), nullable=False, index=True)
    action_type_id = Column(Integer, ForeignKey(
        "xp_action_types.id"), nullable=False, index=True)
    xp_awarded = Column(Integer, nullable=False)
    reference_type = Column(String, nullable=True)
    reference_id = Column(Integer, nullable=True)

    user = relationship("User", back_populates="xp_events")
    action_type = relationship("XPActionType", back_populates="events")

    @hybrid_property
    def action_key(self) -> str | None:
        """The action type's stable key, for API responses."""
        return self.action_type.key if self.action_type else None
