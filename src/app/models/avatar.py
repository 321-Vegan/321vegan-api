from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from app.database.base_class import Base


class Avatar(Base):
    """Catalog of avatars: the free bundled set plus jeton-unlockable ones.

    `weight` drives the odds of a jeton pull landing on this avatar
    (higher = more common) among non-default avatars — a raw number
    rather than a fixed rarity tier, so odds can be tuned per-avatar via
    PATCH /avatars/{key} without a deploy, the same approach as
    XPActionType.base_xp. `is_default` avatars are free for everyone
    (the original bundled set), never appear in the pull pool, and are
    always valid to equip.
    """
    __tablename__ = "avatars"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    key = Column(String, unique=True, index=True, nullable=False)
    label = Column(String, nullable=False)
    weight = Column(Integer, nullable=False, default=0)
    is_default = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    unlocks = relationship("UserAvatar", back_populates="avatar")


class UserAvatar(Base):
    """One avatar a user has unlocked via a jeton pull.

    Only records premium (non-default) unlocks — default avatars are
    always available and don't need a row here.
    """
    __tablename__ = "user_avatars"
    __table_args__ = (
        UniqueConstraint("user_id", "avatar_id", name="uq_user_avatar"),
    )

    id = Column(Integer, primary_key=True, index=True)
    unlocked_at = Column(DateTime, default=datetime.now, nullable=False)
    user_id = Column(Integer, ForeignKey(
        "users.id", ondelete="CASCADE"), nullable=False, index=True)
    avatar_id = Column(Integer, ForeignKey(
        "avatars.id", ondelete="CASCADE"), nullable=False, index=True)

    user = relationship("User", back_populates="unlocked_avatars")
    avatar = relationship("Avatar", back_populates="unlocks")
