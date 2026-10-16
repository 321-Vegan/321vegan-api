import enum
from datetime import datetime
from sqlalchemy import Column, Integer, SmallInteger, String, Boolean, Enum, DateTime, func
from sqlalchemy.orm import relationship, object_session, with_parent
from sqlalchemy.ext.hybrid import hybrid_method
from app.database.base_class import Base
from app.models.subscription import SubscriptionStatus
from app.models.checking import Checking
from app.models.error_report import ErrorReport
from app.models.product_review import ProductReview


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
    product_reviews = relationship("ProductReview", back_populates="user")
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

    def _count(self, model, relationship_attr) -> int:
        """Count the user's rows of a relationship without loading them"""
        session = object_session(self)
        if session is None:
            return 0
        return session.query(func.count(model.id)).filter(
            with_parent(self, relationship_attr)).scalar() or 0

    @property
    def nb_checkings(self) -> int:
        """Return the number of checkings made by the user"""
        return self._count(Checking, User.checkings)

    @property
    def nb_error_reports(self) -> int:
        """Return the number of error reports made by the user"""
        return self._count(ErrorReport, User.error_reports)

    @property
    def nb_product_reviews(self) -> int:
        """Return the number of product reviews posted by the user"""
        return self._count(ProductReview, User.product_reviews)

    @property
    def subscription_status(self):
        """Return the status of the user's latest subscription, or None"""
        if not self.subscriptions:
            return None
        latest = max(self.subscriptions,
                     key=lambda s: s.created_at or datetime.min)
        return latest.status

    @property
    def is_premium(self) -> bool:
        """Return True if the user has premium access (bypass or active/grace subscription)"""
        if self.subscription_bypass:
            return True
        return self.subscription_status in (SubscriptionStatus.ACTIVE, SubscriptionStatus.GRACE_PERIOD)

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
