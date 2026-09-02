from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..auth import claims_from_request, upsert_user
from ..db import get_db
from ..gamification import award
from ..models import (FocusSession, Note, Notebook, PointEvent, Quiz,
                      QuizAttempt, Room, RoomMember, Source, User, Violation)
from .rooms import manager as room_manager
from .rooms import _finalize

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _get_admin(db: Session, uid: str) -> User:
    user = db.get(User, uid)
    if not user or not user.is_admin:
        raise HTTPException(403, "Admin access required")
    return user


async def require_admin(request: Request, db: Session = Depends(get_db)) -> User:
    claims = claims_from_request(request)
    user = await run_in_threadpool(upsert_user, db, claims)
    if not user.is_admin:
        raise HTTPException(403, "Admin access required")
    return user


# ---------- overview ----------

@router.get("/overview")
async def overview(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    day_ago = datetime.utcnow() - timedelta(hours=24)
    online_now = sum(room_manager.member_count(code) for code in room_manager.rooms)
    sessions_running = sum(
        1 for st in room_manager.states.values() if st.phase == "running"
    )
    return {
        "users": db.query(func.count(User.id)).scalar(),
        "rooms": db.query(func.count(Room.id)).scalar(),
        "online_now": online_now,
        "sessions_running": sessions_running,
        "sessions_completed_24h": db.query(func.count(FocusSession.id)).filter(
            FocusSession.status == "completed",
            FocusSession.ended_at >= day_ago).scalar() or 0,
        "notes": db.query(func.count(Note.id)).scalar(),
        "quiz_attempts": db.query(func.count(QuizAttempt.id)).scalar(),
        "points_total": db.query(func.coalesce(func.sum(User.points), 0)).scalar(),
    }


# ---------- users ----------

class UserPatch(BaseModel):
    display_name: str | None = None
    email: str | None = None
    is_admin: bool | None = None


class PointsAdjust(BaseModel):
    delta: int
    reason: str = "admin-adjustment"


def _user_row(u: User, notes_count: int = 0) -> dict:
    return {
        "id": u.id, "display_name": u.display_name, "email": u.email,
        "points": u.points, "current_streak": u.current_streak,
        "longest_streak": u.longest_streak, "is_admin": bool(u.is_admin),
        "notes": notes_count, "created_at": str(u.created_at),
        "last_active": str(u.last_active or ""),
    }


@router.get("/users")
async def list_users(q: str = "", admin: User = Depends(require_admin),
                     db: Session = Depends(get_db)):
    query = db.query(User)
    if q:
        like = f"%{q}%"
        query = query.filter((User.display_name.ilike(like)) |
                             (User.email.ilike(like)) | (User.id.ilike(like)))
    users = query.order_by(User.created_at.desc()).limit(200).all()
    counts = dict(db.query(Note.user_id, func.count(Note.id)).group_by(Note.user_id).all())
    return [_user_row(u, counts.get(u.id, 0)) for u in users]


@router.patch("/users/{user_id}")
async def patch_user(user_id: str, body: UserPatch,
                     admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "User not found")
    if body.display_name is not None:
        target.display_name = body.display_name.strip()[:60] or target.display_name
    if body.email is not None:
        target.email = body.email.strip()
    if body.is_admin is not None:
        if target.id == admin.id and not body.is_admin:
            raise HTTPException(400, "You cannot revoke your own admin role")
        target.is_admin = body.is_admin
    db.commit()
    return _user_row(target)


@router.post("/users/{user_id}/points")
async def adjust_points(user_id: str, body: PointsAdjust,
                        admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "User not found")
    result = award(db, target, body.delta, f"admin:{body.reason[:60]}")
    db.commit()
    return {**result, "reason": body.reason}


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, admin: User = Depends(require_admin),
                      db: Session = Depends(get_db)):
    if user_id == admin.id:
        raise HTTPException(400, "You cannot delete your own account here")
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "User not found")

    notebooks = db.query(Notebook).filter(Notebook.user_id == user_id).all()
    for nb in notebooks:
        db.query(Source).filter(Source.notebook_id == nb.id).delete()
        db.query(Quiz).filter(Quiz.notebook_id == nb.id).delete()
    db.query(Notebook).filter(Notebook.user_id == user_id).delete()
    db.query(QuizAttempt).filter(QuizAttempt.user_id == user_id).delete()
    db.query(Quiz).filter(Quiz.user_id == user_id).delete()
    db.query(Note).filter(Note.user_id == user_id).delete()
    db.query(PointEvent).filter(PointEvent.user_id == user_id).delete()
    db.query(RoomMember).filter(RoomMember.user_id == user_id).delete()
    db.commit()

    for code in list(room_manager.rooms):
        for ws, uid, _name in list(room_manager.members(code)):
            if uid == user_id:
                try:
                    await ws.close(code=4403, reason="Account removed")
                except Exception:
                    pass
                room_manager.remove(code, ws)

    db.delete(target)
    db.commit()
    return {"ok": True}


# ---------- rooms ----------

def _room_row(r: Room, host_name: str) -> dict:
    state = room_manager.state(r.code)
    return {
        "code": r.code, "name": r.name, "host_id": r.host_id,
        "host_name": host_name, "is_public": bool(r.is_public),
        "duration_default": r.duration_default,
        "members_db": db_member_count(r.code), "online": room_manager.member_count(r.code),
        "phase": state.phase, "created_at": str(r.created_at),
    }


def db_member_count(code: str) -> int:
    from ..db import SessionLocal

    db = SessionLocal()
    try:
        room = db.query(Room).filter(Room.code == code).first()
        if not room:
            return 0
        return db.query(func.count()).select_from(RoomMember).filter(
            RoomMember.room_id == room.id).scalar() or 0
    finally:
        db.close()


@router.get("/rooms")
async def list_rooms(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    rooms = db.query(Room).order_by(Room.created_at.desc()).limit(100).all()
    hosts = {u.id: u.display_name for u in
             db.query(User).filter(User.id.in_([r.host_id for r in rooms])).all()} if rooms else {}
    return [_room_row(r, hosts.get(r.host_id, r.host_id or "?")) for r in rooms]


@router.post("/rooms/{code}/end")
async def end_room(code: str, admin: User = Depends(require_admin),
                   db: Session = Depends(get_db)):
    code = code.upper()
    room = db.query(Room).filter(Room.code == code).first()
    if not room:
        raise HTTPException(404, "Room not found")
    state = room_manager.state(code)
    was_running = state.phase == "running"
    if was_running:
        await _finalize(code, "ended_by_admin")
    else:
        await room_manager.broadcast(code, {"type": "room_closed", "detail": "closed by admin"})
    return {"ok": True, "finalized": was_running}


@router.delete("/rooms/{code}")
async def delete_room(code: str, admin: User = Depends(require_admin),
                      db: Session = Depends(get_db)):
    code = code.upper()
    room = db.query(Room).filter(Room.code == code).first()
    if not room:
        raise HTTPException(404, "Room not found")

    await room_manager.broadcast(code, {"type": "room_closed", "detail": "room deleted"})
    db.query(RoomMember).filter(RoomMember.room_id == room.id).delete()
    db.delete(room)
    db.commit()

    room_manager.rooms.pop(code, None)
    room_manager.states.pop(code, None)
    room_manager.hosts.pop(code, None)
    return {"ok": True}
