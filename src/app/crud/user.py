from typing import Optional, List
from datetime import datetime, timedelta

import sentry_sdk
from sqlalchemy import func, desc
from sqlalchemy.orm import Session

from app.crud.base import CRUDRepository
from app.models.user import User, UserRole
from app.models.checking import Checking
from app.security import verify_password, get_password_hash, generate_reset_token
from app.config import settings


class UserCRUDRepository(CRUDRepository):
    def get_user_by_email(self, db: Session, email: str) -> Optional[User]:
        """
        Get a user by email.

        Parameters:
            db (Session): The database session.
            email (str): The email of the user.

        Returns:
            Optional[User]: The user found by email, or None if not found.
        """
        results = (
            db.query(self._model)
            .filter(
                func.lower(self._model.email) == email.lower(),
                self._model.is_active == True,
            )
            .all()
        )
        if len(results) > 1:
            sentry_sdk.capture_message(
                f"Multiple active accounts found for email {email.lower()}",
                level="error",
            )
            return None
        return results[0] if results else None

    @staticmethod
    def is_super_user(user: User) -> bool:
        """
        Check if the given user is a super user (admin).

        Parameters:
            user (User): The user to check.

        Returns:
            bool: True if the user is a super user, False otherwise.
        """
        return user.role == UserRole.ADMIN

    @staticmethod
    def is_active_user(user: User) -> bool:
        """
        Check if a user is active.

        Parameters:
            user (User): The user object to check.

        Returns:
            bool: True if the user is active, False otherwise.
        """
        return user.is_active

    @staticmethod
    def deactivate_user(db: Session, user: User) -> User:
        """Deactivates a user by setting their `is_active` flag to `False`.

        Parameters:
            db (Session): The database session object.
            user (User): The user to deactivate.

        Returns:
            User: The deactivated user object.
        """
        user.is_active = False
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    def authenticate_user(
        self, db: Session, email: str, password: str
    ) -> Optional[User]:
        """
        Authenticates a user with the given email and password.

        Parameters:
            db (Session): The database session object.
            email (str): The email of the user.
            password (str): The password of the user.

        Returns:
            Optional[User]: The authenticated user if successful, None otherwise.
        """
        user = self.get_user_by_email(db, email)
        if not user:
            return None
        if not verify_password(password, user.password):
            return None
        return user
    
    def create_password_reset_token(self, db: Session, email: str) -> Optional[str]:
        """
        Create a password reset token for a user with the given email.

        Parameters:
            db (Session): The database session object.
            email (str): The email of the user.

        Returns:
            Optional[str]: The reset token if user exists, None otherwise.
        """
        user = self.get_user_by_email(db, email)
        if not user:
            return None
        
        # Generate reset token
        reset_token = generate_reset_token()
        
        # Set token and expiration
        user.reset_token = reset_token
        user.reset_token_expires = datetime.utcnow() + timedelta(hours=settings.RESET_TOKEN_EXPIRE_HOURS)
        
        db.add(user)
        db.commit()
        db.refresh(user)
        
        return reset_token
    
    def verify_reset_token(self, db: Session, token: str) -> Optional[User]:
        """
        Verify a password reset token and return the associated user.

        Parameters:
            db (Session): The database session object.
            token (str): The reset token to verify.

        Returns:
            Optional[User]: The user if token is valid, None otherwise.
        """
        user = self.get_one(db, User.reset_token == token)
        if not user:
            return None
        
        # Check if token has expired
        if not user.reset_token_expires or user.reset_token_expires < datetime.now():
            return None
            
        return user
    
    def reset_password(self, db: Session, token: str, new_password: str) -> Optional[User]:
        """
        Reset a user's password using a reset token.

        Parameters:
            db (Session): The database session object.
            token (str): The reset token.
            new_password (str): The new password.

        Returns:
            Optional[User]: The user if password was reset successfully, None otherwise.
        """
        user = self.verify_reset_token(db, token)
        if not user:
            return None
        
        # Update password and clear reset token
        user.password = get_password_hash(new_password)
        user.reset_token = None
        user.reset_token_expires = None
        
        db.add(user)
        db.commit()
        db.refresh(user)
        
        return user
    
    def request_email_change(self, db: Session, user: User, new_email: str) -> Optional[str]:
        """
        Request an email change for a user.
 
        Parameters:
            db (Session): The database session object.
            user (User): The user requesting the change.
            new_email (str): The new email address.
 
        Returns:
            Optional[str]: The email change token if successful, None if email is taken.
        """
        existing_user = self.get_user_by_email(db, new_email)
        if existing_user:
            return None
 
        token = generate_reset_token()
 
        user.pending_email = new_email
        user.email_change_token = token
        user.email_change_expires = datetime.utcnow() + timedelta(hours=settings.RESET_TOKEN_EXPIRE_HOURS)
 
        db.add(user)
        db.commit()
        db.refresh(user)
 
        return token
 
    def confirm_email_change(self, db: Session, token: str) -> tuple[Optional[User], Optional[str]]:
        """
        Confirm an email change using a token.
 
        Parameters:
            db (Session): The database session object.
            token (str): The email change token.
 
        Returns:
            tuple[Optional[User], Optional[str]]: The user and old email if successful, (None, None) otherwise.
        """
        user = self.get_one(db, User.email_change_token == token)
        if not user:
            return None, None
 
        if not user.email_change_expires or user.email_change_expires < datetime.now():
            return None, None

        old_email = user.email
        user.email = user.pending_email
        user.pending_email = None
        user.email_change_token = None
        user.email_change_expires = None
 
        db.add(user)
        db.commit()
        db.refresh(user)
 
        return user, old_email

    def get_leaderboard(self, db: Session, sortby: str = "nb_products_modified", limit: int = 20) -> List[User]:
        checking_count = (
            db.query(Checking.user_id, func.count(Checking.id).label("nb_checkings_count"))
            .group_by(Checking.user_id)
            .subquery()
        )
        query = (
            db.query(User)
            .outerjoin(checking_count, User.id == checking_count.c.user_id)
            .filter(User.is_active == True)
        )
        if sortby == "nb_checkings":
            query = query.order_by(desc(func.coalesce(checking_count.c.nb_checkings_count, 0)))
        else:
            query = query.order_by(desc(User.nb_products_modified))
        return query.limit(limit).all()

    def increment_products_sent(self, db: Session, user_id: int):
        """
        Increment the nb_products_sent counter for a user.

        Parameters:
            db (Session): The database session.
            user_id (int): The ID of the user.

        Returns:
            Optional[User]: The updated user, or None if not found.
        """
        user = self.get_one(db, self._model.id == user_id)
        if user:
            current_count = user.nb_products_sent or 0
            user.nb_products_sent = current_count + 1
            db.add(user)
            db.commit()
            db.refresh(user)

    def increment_scan_count(self, db: Session, user_id: int, count: int = 1) -> Optional[int]:
        """
        Increment the scan_count counter for a user.

        Parameters:
            db (Session): The database session.
            user_id (int): The ID of the user.
            count (int): How many scans to add (batched offline scans).

        Returns:
            Optional[int]: The new scan count, or None if the user was not found.
        """
        user = self.get_one(db, self._model.id == user_id)
        if user is None:
            return None
        user.scan_count = (user.scan_count or 0) + count
        db.add(user)
        db.commit()
        db.refresh(user)
        return user.scan_count

    def initialize_scan_count(self, db: Session, user_id: int, count: int) -> Optional[int]:
        """
        Seed the scan_count counter for a user from the app's local count.

        Only applies if the counter is still 0 (fresh account), so an
        already-established count cannot be overwritten.

        Parameters:
            db (Session): The database session.
            user_id (int): The ID of the user.
            count (int): The initial scan count from the app.

        Returns:
            Optional[int]: The resulting scan count, or None if the user was not found.
        """
        user = self.get_one(db, self._model.id == user_id)
        if user is None:
            return None
        if not user.scan_count:
            user.scan_count = count
            db.add(user)
            db.commit()
            db.refresh(user)
        return user.scan_count

    def record_daily_checkin(self, db: Session, user_id: int) -> Optional[dict]:
        """
        Record a daily check-in and update the user's login streak.

        - Already checked in today: no-op, returns the current streak.
        - Last check-in was yesterday: streak increments.
        - Any bigger gap (or first-ever check-in): streak resets to 1.

        Parameters:
            db (Session): The database session.
            user_id (int): The ID of the user.

        Returns:
            Optional[dict]: {"streak_count": int, "is_new_day": bool}, or
                None if the user was not found.
        """
        user = self.get_one(db, self._model.id == user_id)
        if user is None:
            return None

        # Lock the row: without this, two near-simultaneous check-ins
        # (e.g. two devices on the same account) could both read
        # last_login_streak_date as "not today" and both increment the
        # streak, double-counting one day.
        db.query(self._model).filter(
            self._model.id == user_id).with_for_update().one()

        today = datetime.now().date()
        if user.last_login_streak_date == today:
            return {"streak_count": user.login_streak_count, "is_new_day": False}

        if user.last_login_streak_date == today - timedelta(days=1):
            user.login_streak_count = (user.login_streak_count or 0) + 1
        else:
            user.login_streak_count = 1

        user.last_login_streak_date = today
        db.add(user)
        db.commit()
        db.refresh(user)
        return {"streak_count": user.login_streak_count, "is_new_day": True}


user_crud = UserCRUDRepository(model=User)