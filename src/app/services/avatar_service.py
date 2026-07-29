import random
from typing import Optional
from sqlalchemy import update
from sqlalchemy.orm import Session
from app.crud.avatar import avatar_crud, user_avatar_crud
from app.models.avatar import Avatar
from app.models.user import User
from app.log import get_logger

log = get_logger(__name__)


def can_equip(db: Session, user_id: int, avatar_key: str) -> bool:
    """
    Whether a user is allowed to set User.avatar to `avatar_key`.

    True for default (free) avatars, and for premium avatars the user
    has unlocked via a jeton pull. False for an unknown/inactive key or
    a premium avatar the user hasn't unlocked — used to stop a client
    from equipping an avatar it never paid for.

    Parameters:
        db (Session): The database session.
        user_id (int): The user ID.
        avatar_key (str): The avatar key the user is trying to equip.

    Returns:
        bool: True if the user may equip this avatar.
    """
    avatar = avatar_crud.get_by_key(db, avatar_key)
    if avatar is None or not avatar.is_active:
        return False
    if avatar.is_default:
        return True
    return user_avatar_crud.owns(db, user_id, avatar.id)


def pull_avatar(db: Session, user: User) -> Optional[dict]:
    """
    Spend one jeton on a weighted-random avatar pull.

    Duplicates are allowed by design: the draw is always over every
    active, non-default avatar (not just unowned ones), so the
    configured odds never silently shift as a user's collection grows.
    A pull that lands on an already-owned avatar still spends the
    jeton and returns is_new=False.

    Parameters:
        db (Session): The database session.
        user (User): The user spending a jeton.

    Returns:
        Optional[dict]: {"avatar": Avatar, "is_new": bool,
            "jetons_remaining": int}, or None if the user has no jetons
            to spend.

    Raises:
        RuntimeError: If no avatar is currently pullable (a catalog
            misconfiguration — every premium avatar is inactive or has
            weight 0). The jeton is refunded before raising. Deliberately
            distinct from the None case: this is a server-side config
            problem, not "you don't have enough jetons", and callers
            shouldn't report it to the user as the latter.
    """
    # Atomic check-and-decrement: only succeeds if the user still has a
    # jeton at the moment of the UPDATE, so two concurrent pulls can't
    # both spend the same last jeton.
    result = db.execute(
        update(User)
        .where(User.id == user.id, User.jetons >= 1)
        .values(jetons=User.jetons - 1)
    )
    db.commit()
    if result.rowcount == 0:
        db.refresh(user)
        return None

    # weight <= 0 avatars are excluded rather than passed to
    # random.choices, which raises if every weight is zero.
    pool = [a for a in avatar_crud.get_pullable(db) if a.weight > 0]
    if not pool:
        log.error(
            "No pullable avatars configured — refunding jeton for user %s", user.id)
        db.execute(
            update(User).where(User.id == user.id).values(jetons=User.jetons + 1)
        )
        db.commit()
        db.refresh(user)
        raise RuntimeError("No avatars are currently configured for unlocking")

    won: Avatar = random.choices(
        pool, weights=[a.weight for a in pool], k=1)[0]
    _, is_new = user_avatar_crud.unlock(db, user.id, won.id)

    db.refresh(user)
    log.debug(
        "user %s pulled avatar %s (new=%s), %s jeton(s) remaining",
        user.id, won.key, is_new, user.jetons,
    )
    return {"avatar": won, "is_new": is_new, "jetons_remaining": user.jetons}
