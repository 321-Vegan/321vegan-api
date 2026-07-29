import enum
from datetime import datetime
from sqlalchemy import Column, Integer, SmallInteger, String, Boolean, Enum, DateTime, Date
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_method
from app.database.base_class import Base
from app.xp_leveling import level_for_xp, xp_to_next_level as compute_xp_to_next_level


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    CONTRIBUTOR = "contributor"
    USER = "user"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    role = Column(Enum(UserRole), default=UserRole.USER)
    nickname = Column(String, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    password = Column(String, nullable=False)
    is_active = Column(Boolean, default=False)
    avatar = Column(String, nullable=True)
    vegan_since = Column(DateTime, nullable=True)
    nb_products_sent = Column(Integer, default=0)
    nb_products_modified = Column(Integer, default=0)
    supporter = Column(SmallInteger, default=0, nullable=False)
    subscription_bypass = Column(Boolean, default=False, nullable=False)
    scan_count = Column(Integer, default=0, server_default="0", nullable=False)
    xp = Column(Integer, default=0, server_default="0", nullable=False)
    login_streak_count = Column(
        Integer, default=0, server_default="0", nullable=False)
    last_login_streak_date = Column(Date, nullable=True)
    jetons = Column(Integer, default=0, server_default="0", nullable=False)
    reset_token = Column(String, nullable=True)
    reset_token_expires = Column(DateTime, nullable=True)
    pending_email = Column(String, nullable=True)
    email_change_token = Column(String, nullable=True)
    email_change_expires = Column(DateTime, nullable=True)
    checkings = relationship("Checking",
                             back_populates="user",
                             cascade="all, delete",
                             passive_deletes=True,)
    error_reports = relationship("ErrorReport", back_populates="user")
    shops = relationship("Shop", back_populates="user")
    shop_reviews = relationship("ShopReview", back_populates="user")
    scan_events = relationship("ScanEvent", back_populates="user")
    not_found_reports = relationship(
        "ProductNotFoundReport", back_populates="user")
    found_reports = relationship(
        "ProductFoundReport", back_populates="user")
    subscriptions = relationship(
        "Subscription", back_populates="user")
    b12_intakes = relationship(
        "B12Intake", back_populates="user",
        cascade="all, delete",
        passive_deletes=True,)
    xp_events = relationship(
        "XPEvent", back_populates="user",
        cascade="all, delete",
        passive_deletes=True,)
    unlocked_avatars = relationship(
        "UserAvatar", back_populates="user",
        cascade="all, delete",
        passive_deletes=True,)

    @property
    def nb_checkings(self) -> int:
        """Return the number of checkings made by the user"""
        return len(self.checkings) if self.checkings else 0

    @property
    def nb_error_reports(self) -> int:
        """Return the number of error reports made by the user"""
        return len(self.error_reports) if self.error_reports else 0

    @property
    def subscription_status(self):
        """Return the status of the user's latest subscription, or None"""
        if not self.subscriptions:
            return None
        latest = max(self.subscriptions,
                     key=lambda s: s.created_at or datetime.min)
        return latest.status

    @property
    def level(self) -> int:
        """Current XP level, derived from total xp (see app.xp_leveling)."""
        return level_for_xp(self.xp or 0)

    @property
    def xp_to_next_level(self) -> int:
        """XP still needed to reach the next level."""
        return compute_xp_to_next_level(self.xp or 0)

    @property
    def roles(self) -> list:
        roles = list(UserRole)
        index = roles.index(self.role)
        return roles[index:]

    @hybrid_method
    def is_user_active(self) -> bool:
        return self.is_active

    @hybrid_method
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN

    @hybrid_method
    def is_contributor(self) -> bool:
        return self.role == UserRole.CONTRIBUTOR

    @hybrid_method
    def has_role(self, role) -> bool:
        return role in self.roles()
