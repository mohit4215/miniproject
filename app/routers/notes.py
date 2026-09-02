from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth import claims_from_request, upsert_user
from ..db import get_db
from ..gamification import award, touch_streak
from ..models import Note

router = APIRouter(prefix="/api/notes", tags=["notes"])


class NoteBody(BaseModel):
    title: str
    content: str = ""
    tags: str = ""


@router.get("")
async def list_notes(q: str = "", db: Session = Depends(get_db),
                     claims: dict = Depends(claims_from_request)):
    user = await run_in_threadpool(upsert_user, db, claims)
    query = db.query(Note).filter(Note.user_id == user.id)
    if q:
        like = f"%{q}%"
        query = query.filter((Note.title.ilike(like)) | (Note.content.ilike(like)) | (Note.tags.ilike(like)))
    notes = query.order_by(Note.updated_at.desc()).limit(200).all()
    return [{"id": n.id, "title": n.title, "tags": n.tags, "updated_at": str(n.updated_at)} for n in notes]


@router.post("")
async def create_note(body: NoteBody, db: Session = Depends(get_db),
                      claims: dict = Depends(claims_from_request)):
    user = await run_in_threadpool(upsert_user, db, claims)
    note = Note(user_id=user.id, title=body.title.strip()[:200] or "Untitled",
                content=body.content, tags=body.tags.strip())
    db.add(note)
    result = award(db, user, 5, "note-created", ref=note.id)
    streak = touch_streak(db, user)
    db.commit()
    db.refresh(note)
    return {"id": note.id, "points": result, "streak": streak}


@router.get("/{note_id}")
async def get_note(note_id: str, db: Session = Depends(get_db),
                   claims: dict = Depends(claims_from_request)):
    user = await run_in_threadpool(upsert_user, db, claims)
    note = db.get(Note, note_id)
    if not note or note.user_id != user.id:
        raise HTTPException(404, "Note not found")
    return {"id": note.id, "title": note.title, "content": note.content,
            "tags": note.tags, "created_at": str(note.created_at), "updated_at": str(note.updated_at)}


@router.put("/{note_id}")
async def update_note(note_id: str, body: NoteBody, db: Session = Depends(get_db),
                      claims: dict = Depends(claims_from_request)):
    from datetime import datetime

    user = await run_in_threadpool(upsert_user, db, claims)
    note = db.get(Note, note_id)
    if not note or note.user_id != user.id:
        raise HTTPException(404, "Note not found")
    note.title = body.title.strip()[:200] or note.title
    note.content = body.content
    note.tags = body.tags.strip()
    note.updated_at = datetime.utcnow()
    db.commit()
    return {"ok": True}


@router.delete("/{note_id}")
async def delete_note(note_id: str, db: Session = Depends(get_db),
                      claims: dict = Depends(claims_from_request)):
    user = await run_in_threadpool(upsert_user, db, claims)
    note = db.get(Note, note_id)
    if not note or note.user_id != user.id:
        raise HTTPException(404, "Note not found")
    db.delete(note)
    db.commit()
    return {"ok": True}
