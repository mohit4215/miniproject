from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import claims_from_request, upsert_user
from ..db import get_db
from ..gamification import level_for, level_progress, touch_streak
from ..models import FocusSession, Note, PointEvent, QuizAttempt, User

router = APIRouter(prefix="/api/gamify", tags=["gamify"])


@router.get("/profile")
async def profile(db: Session = Depends(get_db), claims: dict = Depends(claims_from_request)):
    user = await run_in_threadpool(upsert_user, db, claims)
    streak = touch_streak(db, user)
    db.commit()
    sessions = db.query(func.count(FocusSession.id)).filter(
        FocusSession.started_by == user.id).scalar() or 0
    quizzes = db.query(func.count(QuizAttempt.id)).filter(QuizAttempt.user_id == user.id).scalar() or 0
    notes = db.query(func.count(Note.id)).filter(Note.user_id == user.id).scalar() or 0
    events = (db.query(PointEvent)
              .filter(PointEvent.user_id == user.id)
              .order_by(PointEvent.created_at.desc())
              .limit(12).all())
    return {
        "user_id": user.id,
        "display_name": user.display_name,
        "is_admin": bool(user.is_admin),
        "points": user.points,
        "level": level_progress(user.points),
        "current_streak": user.current_streak,
        "longest_streak": user.longest_streak,
        "streak_today": streak,
        "totals": {"focus_sessions": sessions, "quizzes": quizzes, "notes": notes},
        "recent_events": [{"delta": e.delta, "reason": e.reason, "at": str(e.created_at)} for e in events],
    }


@router.get("/leaderboard")
async def leaderboard(scope: str = "global", code: str = "", db: Session = Depends(get_db)):
    users = (db.query(User)
             .filter(User.points > 0)
             .order_by(User.points.desc())
             .limit(20).all())
    return [
        {"rank": i + 1, "display_name": u.display_name or u.id[:8],
         "points": u.points, "level": level_for(u.points),
         "current_streak": u.current_streak}
        for i, u in enumerate(users)
    ]
