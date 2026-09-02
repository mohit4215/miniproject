import math
from datetime import date, timedelta

from sqlalchemy.orm import Session

from .config import settings
from .models import PointEvent, User

STREAK_BONUS = 20
STREAK_MILESTONE = 7
MILESTONE_BONUS = 50


def level_for(points: int) -> int:
    if points < 0:
        points = 0
    return int(math.isqrt(points // 250)) + 1


def level_floor(level: int) -> int:
    return (level - 1) ** 2 * 250


def level_progress(points: int) -> dict:
    lvl = level_for(points)
    floor = level_floor(lvl)
    nxt = level_floor(lvl + 1)
    span = max(1, nxt - floor)
    into = max(0, min(points - floor, span))
    return {"level": lvl, "floor": floor, "next": nxt, "pct": round(into / span * 100)}


def award(db: Session, user: User, delta: int, reason: str, ref: str = "") -> dict:
    before = level_for(user.points)
    user.points = max(0, user.points + delta)
    db.add(PointEvent(user_id=user.id, delta=delta, reason=reason, ref=ref))
    return {
        "delta": delta,
        "points": user.points,
        "level_before": before,
        "level_after": level_for(user.points),
        "level_up": level_for(user.points) > before,
    }


def touch_streak(db: Session, user: User) -> dict:
    today = date.today()
    if user.last_active == today:
        return {"current": user.current_streak, "bonus": 0}
    if user.last_active == today - timedelta(days=1):
        user.current_streak += 1
    else:
        user.current_streak = 1
    if user.current_streak > user.longest_streak:
        user.longest_streak = user.current_streak
    user.last_active = today
    bonus = 0
    if user.current_streak > 1:
        bonus += STREAK_BONUS
    if user.current_streak % STREAK_MILESTONE == 0:
        bonus += MILESTONE_BONUS
    result = {"current": user.current_streak, "bonus": 0}
    if bonus:
        award(db, user, bonus, f"streak-day-{user.current_streak}")
        result["bonus"] = bonus
    return result


def focus_points(duration_min: int, violations: int) -> int:
    earned = min(duration_min * settings.focus_points_per_minute, settings.focus_points_cap)
    base = max(settings.participation_points, earned)
    return max(0, base - violations * settings.violation_penalty)
