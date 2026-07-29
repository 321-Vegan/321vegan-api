from typing import Optional
from sqlalchemy import update
from sqlalchemy.orm import Session
from app.models.user import User
from app.models.subscription import SubscriptionStatus
from app.models.xp import XPActionType, XPEvent
from app.xp_leveling import level_for_xp
from app.log import get_logger

log = get_logger(__name__)

# Flat XP boost applied to every action for users with an active
# subscription (or a subscription bypass, e.g. testers/VIPs).
SUBSCRIBER_XP_MULTIPLIER = 1.5

# Daily check-in XP ramps linearly with the streak (day N grants
# daily_login.base_xp * N) up to this many days, then plateaus — a
# streak keeps growing past this, but the XP reward stops increasing.
DAILY_LOGIN_XP_CAP_DAYS = 7

# Jetons (avatar-unlock currency) granted per level gained.
JETONS_PER_LEVEL = 1


class XPAction:
    """Stable keys for the actions that award XP.

    Must match the `key` column of the seeded xp_action_types rows (see
    the migration that creates the table). Adding a new XP-earning action
    means: a constant here, a seeded row in a migration, and a call to
    award_xp() at the point the action happens.
    """
    BASIC_SCAN = "basic_scan"
    VEGANDEX_SCAN = "vegandex_scan"
    VEGANDEX_SCAN_FIRST_IN_SHOP = "vegandex_scan_first_in_shop"
    SHOP_REVIEW = "shop_review"
    PRODUCT_INFO_NO_PHOTO = "product_info_no_photo"
    PRODUCT_INFO_WITH_PHOTO = "product_info_with_photo"
    B12_INTAKE = "b12_intake"
    ERROR_REPORT = "error_report"
    DAILY_LOGIN = "daily_login"


def _is_subscriber(user: User) -> bool:
    """Whether `user` qualifies for the subscriber XP boost."""
    return user.subscription_status == SubscriptionStatus.ACTIVE or bool(
        user.subscription_bypass)


def award_xp(
    db: Session,
    user: User,
    action_key: str,
    reference_type: Optional[str] = None,
    reference_id: Optional[int] = None,
    quantity: int = 1,
) -> int:
    """
    Award XP to a user for a given action.

    Looks up the base value for `action_key` in xp_action_types, applies
    the subscriber boost, records an XPEvent, and updates the user's
    cached total. Never raises: an unknown or inactive action type is
    logged and treated as a 0-XP no-op, so the triggering action (a scan,
    a review, ...) always succeeds regardless of XP config state.

    Parameters:
        db (Session): The database session.
        user (User): The user to credit.
        action_key (str): One of the XPAction constants.
        reference_type (str | None): Kind of entity that triggered the
            award (e.g. "scan_event"), kept for the audit trail.
        reference_id (int | None): ID of that entity.
        quantity (int): Number of times the action happened in this one
            grant (e.g. batched offline scans synced in one call).
            Multiplies the base XP before the subscriber boost.

    Returns:
        int: The XP actually awarded (0 if the action type is unknown or
            inactive).
    """
    action_type = db.query(XPActionType).filter(
        XPActionType.key == action_key).first()

    if action_type is None:
        log.warning("Unknown XP action type: %s", action_key)
        return 0

    if not action_type.is_active:
        log.debug(
            "XP action type %s is disabled, skipping award", action_key)
        return 0

    xp_awarded = action_type.base_xp * quantity
    if _is_subscriber(user):
        xp_awarded = round(xp_awarded * SUBSCRIBER_XP_MULTIPLIER)

    event = XPEvent(
        user_id=user.id,
        action_type_id=action_type.id,
        xp_awarded=xp_awarded,
        reference_type=reference_type,
        reference_id=reference_id,
    )
    db.add(event)

    # Jetons are granted per level crossed by this grant — level isn't
    # stored anywhere, so it's derived from xp before/after here. A big
    # batched grant (e.g. offline-scan sync) can cross several levels at
    # once and should credit all of them, not just one.
    #
    # current_xp is a Python-side read, so under truly concurrent grants
    # for the same user this count could rarely be off by one jeton near
    # a level boundary — deliberately not locked against that: it's a
    # low-stakes, low-probability edge case, and award_xp() is the
    # hottest path in the app, not worth paying for a row lock on every
    # call. The actual xp/jetons totals below are still atomic SQL
    # increments either way, so nothing is ever lost or double-spent.
    current_xp = user.xp or 0
    levels_gained = max(
        0,
        level_for_xp(current_xp + xp_awarded) - level_for_xp(current_xp),
    )
    jetons_gained = levels_gained * JETONS_PER_LEVEL

    update_values = {"xp": User.xp + xp_awarded}
    if jetons_gained:
        update_values["jetons"] = User.jetons + jetons_gained
    db.execute(update(User).where(User.id == user.id).values(**update_values))

    db.commit()
    db.refresh(user)

    log.debug(
        "awarded %s xp (and %s jeton(s)) to user %s for action %s (ref=%s/%s)",
        xp_awarded, jetons_gained, user.id, action_key, reference_type, reference_id,
    )
    return xp_awarded
