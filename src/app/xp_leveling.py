"""
Level curve for the XP system.
"""

XP_PER_LEVEL_STEP = 50


def xp_required_for_level(level: int) -> int:
    """Cumulative XP needed to reach `level` (level 1 requires 0 XP)."""
    if level <= 1:
        return 0
    return XP_PER_LEVEL_STEP * (level - 1) ** 2


def level_for_xp(xp: int) -> int:
    """Compute the highest level reached with the given total XP."""
    level = 1
    while xp_required_for_level(level + 1) <= xp:
        level += 1
    return level


def xp_to_next_level(xp: int) -> int:
    """XP still needed to reach the level right above the current one."""
    current_level = level_for_xp(xp)
    return xp_required_for_level(current_level + 1) - xp
