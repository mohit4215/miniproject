import asyncio
import string
import secrets
import time
from dataclasses import dataclass, field

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import config
from ..auth import claims_from_request, claims_from_ws, upsert_user
from ..db import get_db
from ..gamification import award, focus_points, touch_streak
from ..models import FocusSession, Room, RoomMember, User, Violation

router = APIRouter(prefix="/api/rooms", tags=["rooms"])

_CODE_ALPHABET = string.ascii_uppercase + string.digits


def _gen_code() -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))


class RoomCreate(BaseModel):
    name: str
    duration_default: int = 25
    is_public: bool = True


@router.post("")
async def create_room(
    body: RoomCreate,
    db: Session = Depends(get_db),
    claims: dict = Depends(claims_from_request),
):
    user = await run_in_threadpool(upsert_user, db, claims)
    duration = max(5, min(body.duration_default, 180))
    for _ in range(8):
        code = _gen_code()
        if not db.query(Room).filter(Room.code == code).first():
            break
    room = Room(code=code, name=body.name.strip()[:60], host_id=user.id,
                is_public=body.is_public, duration_default=duration)
    db.add(room)
    db.commit()
    db.refresh(room)
    db.add(RoomMember(room_id=room.id, user_id=user.id))
    db.commit()
    return {"id": room.id, "code": room.code, "name": room.name,
            "host_id": room.host_id, "duration_default": duration}


@router.get("/public")
async def public_rooms(db: Session = Depends(get_db)):
    rooms = db.query(Room).filter(Room.is_public == True).order_by(Room.created_at.desc()).limit(30).all()  # noqa: E712
    return [
        {"code": r.code, "name": r.name, "duration_default": r.duration_default,
         "online": manager.member_count(r.code)}
        for r in rooms
    ]


@router.get("/{code}")
async def room_meta(code: str, db: Session = Depends(get_db)):
    room = db.query(Room).filter(Room.code == code.upper()).first()
    if not room:
        raise HTTPException(404, "Room not found")
    return {"code": room.code, "name": room.name, "host_id": room.host_id,
            "duration_default": room.duration_default,
            "online": manager.member_count(room.code)}


@dataclass
class RoomState:
    phase: str = "idle"
    ends_at: float | None = None
    remaining: float | None = None
    duration_sec: int = 0
    duration_min: int = 0
    session_id: str | None = None
    task: asyncio.Task | None = None
    violations: dict[str, int] = field(default_factory=dict)
    last_violation: dict[str, float] = field(default_factory=dict)


class Manager:
    def __init__(self):
        self.rooms: dict[str, list[tuple[WebSocket, str, str]]] = {}
        self.states: dict[str, RoomState] = {}
        self.hosts: dict[str, str] = {}

    def state(self, code: str) -> RoomState:
        return self.states.setdefault(code, RoomState())

    def add(self, code: str, ws: WebSocket, uid: str, name: str):
        self.rooms.setdefault(code, []).append((ws, uid, name))

    def remove(self, code: str, ws: WebSocket):
        conns = self.rooms.get(code, [])
        self.rooms[code] = [c for c in conns if c[0] is not ws]

    def members(self, code: str) -> list[tuple[WebSocket, str, str]]:
        seen: set[str] = set()
        out = []
        for ws, uid, name in self.rooms.get(code, []):
            if uid not in seen:
                seen.add(uid)
                out.append((ws, uid, name))
        return out

    def member_count(self, code: str) -> int:
        return len({uid for _, uid, _ in self.rooms.get(code, [])})

    async def broadcast(self, code: str, payload: dict):
        dead = []
        for ws, _, _ in list(self.members(code)):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.remove(code, ws)


manager = Manager()


def _persist_session_start(session_id: str, code: str, host_uid: str, dur_min: int):
    from ..db import SessionLocal

    db = SessionLocal()
    try:
        db.add(FocusSession(id=session_id, room_id=code, started_by=host_uid, duration_min=dur_min))
        db.commit()
    finally:
        db.close()


def _persist_finalize(state: RoomState, results: list[dict]):
    from datetime import datetime

    from ..db import SessionLocal

    db = SessionLocal()
    try:
        session = db.get(FocusSession, state.session_id)
        now = datetime.utcnow()
        if session:
            session.status = "completed"
            session.ended_at = now
        rows = []
        for r in results:
            for _ in range(r["violations"]):
                rows.append(Violation(session_id=state.session_id, user_id=r["user_id"],
                                      kind="blur_or_minimize", at=now))
        if rows:
            db.bulk_save_objects(rows)
        db.commit()
    finally:
        db.close()


def _award_results(code: str, dur_min: int) -> list[dict]:
    from ..db import SessionLocal

    state = manager.state(code)
    members = {uid: name for _, uid, name in manager.members(code)}
    results = []
    db = SessionLocal()
    try:
        for uid, count in state.violations.items():
            members.pop(uid, None)
            pts = focus_points(dur_min, count)
            user = db.get(User, uid)
            if user:
                res = award(db, user, pts, f"focus-session:{code}", ref=state.session_id or "")
                touch_streak(db, user)
                results.append({**res, "user_id": uid, "display_name": user.display_name,
                                "violations": count, "points": pts})
        for uid in list(members.keys()):
            user = db.get(User, uid)
            if user:
                pts = focus_points(dur_min, 0)
                res = award(db, user, pts, f"focus-session:{code}",
                            ref=state.session_id or "")
                touch_streak(db, user)
                results.append({**res, "user_id": uid, "display_name": user.display_name,
                                "violations": 0, "points": pts})
        db.commit()
    finally:
        db.close()
    return results


def _cancel_timer(state: RoomState):
    if state.task and not state.task.done():
        state.task.cancel()
    state.task = None


async def _finalize(code: str, reason: str):
    state = manager.state(code)
    _cancel_timer(state)
    if state.phase != "running":
        return
    state.phase = "idle"
    results = await run_in_threadpool(_award_results, code, state.duration_min)
    await run_in_threadpool(_persist_finalize, state, results)
    await manager.broadcast(code, {
        "type": "session_complete", "reason": reason,
        "results": sorted(results, key=lambda r: -r["points"]),
    })


async def _end_later(code: str, at_epoch: float):
    try:
        delay = max(0.05, at_epoch - time.time())
        await asyncio.sleep(delay)
        await _finalize(code, "time_up")
    except asyncio.CancelledError:
        pass


def _start(code: str, uid: str, duration_sec: int, duration_min: int):
    state = manager.state(code)
    _cancel_timer(state)
    state.phase = "running"
    state.duration_sec = duration_sec
    state.duration_min = duration_min
    state.ends_at = time.time() + duration_sec
    state.remaining = None
    state.violations = {}
    state.session_id = f"s{int(time.time()*1000)}{secrets.token_hex(3)}"
    run_bg = asyncio.ensure_future(run_in_threadpool(
        _persist_session_start, state.session_id, code, uid, duration_min))
    state.task = asyncio.create_task(_end_later(code, state.ends_at))
    return run_bg


@router.websocket("/ws/{code}")
async def room_ws(websocket: WebSocket, code: str, token: str | None = None,
                  uid: str | None = None, name: str | None = None,
                  db: Session = Depends(get_db)):
    code = code.upper()
    try:
        claims = claims_from_ws(token, uid, name)
    except HTTPException as exc:
        await websocket.close(code=4401, reason=str(exc.detail))
        return
    user = await run_in_threadpool(upsert_user, db, claims)

    room = await run_in_threadpool(lambda: db.query(Room).filter(Room.code == code).first())
    if not room:
        await websocket.close(code=4404, reason="Room not found")
        return
    if not await run_in_threadpool(
        lambda: db.query(RoomMember)
        .filter(RoomMember.room_id == room.id, RoomMember.user_id == user.id)
        .first()
    ):
        await run_in_threadpool(lambda: (db.add(RoomMember(room_id=room.id, user_id=user.id)), db.commit()))
    manager.hosts.setdefault(code, room.host_id)

    await websocket.accept()
    manager.add(code, websocket, user.id, user.display_name)
    state = manager.state(code)

    async def send(payload):
        await websocket.send_json(payload)

    await send({
        "type": "room_state",
        "phase": state.phase,
        "ends_at": state.ends_at,
        "remaining": state.remaining,
        "duration_sec": state.duration_sec,
        "you": {"user_id": user.id, "display_name": user.display_name},
        "host_id": manager.hosts[code],
        "members": [{"user_id": u, "display_name": n} for _, u, n in manager.members(code)],
        "violations": state.violations,
    })
    await manager.broadcast(code, {
        "type": "presence",
        "members": [{"user_id": u, "display_name": n} for _, u, n in manager.members(code)],
        "joined": user.id,
    })

    try:
        while True:
            msg = await websocket.receive_json()
            mtype = msg.get("type", "")

            if mtype == "start":
                if user.id != manager.hosts.get(code):
                    await send({"type": "error", "detail": "Only the host can start the timer"})
                    continue
                dur_min = max(1, min(int(msg.get("duration_min", 25)), 180))
                dur_sec = max(int(msg.get("duration_sec", 0)), dur_min * 60) if msg.get("duration_sec") else dur_min * 60
                dur_sec = max(5, min(dur_sec, 180 * 60))
                eff_min = max(1, round(dur_sec / 60))
                _start(code, user.id, dur_sec, eff_min)
                await manager.broadcast(code, {
                    "type": "timer_started", "phase": "running",
                    "ends_at": state.ends_at, "duration_sec": state.duration_sec,
                    "started_by": user.display_name,
                })

            elif mtype == "pause":
                if user.id != manager.hosts.get(code) or state.phase != "running":
                    continue
                _cancel_timer(state)
                state.remaining = max(0.0, (state.ends_at or time.time()) - time.time())
                state.phase = "paused"
                await manager.broadcast(code, {"type": "timer_paused", "remaining": state.remaining})

            elif mtype == "resume":
                if user.id != manager.hosts.get(code) or state.phase != "paused":
                    continue
                rem = state.remaining or 0
                state.phase = "running"
                state.ends_at = time.time() + rem
                state.task = asyncio.create_task(_end_later(code, state.ends_at))
                await manager.broadcast(code, {"type": "timer_resumed", "ends_at": state.ends_at})

            elif mtype == "reset":
                if user.id != manager.hosts.get(code):
                    continue
                _cancel_timer(state)
                state.phase = "idle"
                state.ends_at = None
                state.remaining = None
                state.violations = {}
                await manager.broadcast(code, {"type": "timer_reset"})

            elif mtype == "finish_early":
                if user.id != manager.hosts.get(code):
                    continue
                await _finalize(code, "finished_early")

            elif mtype == "violation":
                if state.phase != "running":
                    continue
                now = time.time()
                if now - state.last_violation.get(user.id, 0) < 2.0:
                    continue
                state.last_violation[user.id] = now
                state.violations[user.id] = state.violations.get(user.id, 0) + 1
                await manager.broadcast(code, {
                    "type": "violation", "user_id": user.id,
                    "count": state.violations[user.id],
                    "violations": state.violations,
                })

            elif mtype == "chat":
                text = str(msg.get("text", ""))[:500].strip()
                if text:
                    await manager.broadcast(code, {"type": "chat", "from": user.display_name,
                                                   "text": text, "at": time.time()})

            elif mtype == "ping":
                await send({"type": "pong", "at": time.time()})
    except WebSocketDisconnect:
        pass
    finally:
        manager.remove(code, websocket)
        await manager.broadcast(code, {
            "type": "presence",
            "members": [{"user_id": u, "display_name": n} for _, u, n in manager.members(code)],
            "left": user.id,
        })
