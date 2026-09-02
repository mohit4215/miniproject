import io

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import llm
from ..auth import claims_from_request, upsert_user
from ..config import settings
from ..context_manager import build_messages, estimate_tokens
from ..db import get_db
from ..gamification import award, touch_streak
from ..models import Notebook, Quiz, QuizAttempt, Source, User

router = APIRouter(prefix="/api/notebooks", tags=["notebooks"])


class NotebookCreate(BaseModel):
    title: str


class SourceCreate(BaseModel):
    title: str
    text: str


class ChatBody(BaseModel):
    message: str


class QuizSubmit(BaseModel):
    answers: list[int]


def _owned_notebook(db: Session, user_id: str, notebook_id: str) -> Notebook:
    nb = db.get(Notebook, notebook_id)
    if not nb or nb.user_id != user_id:
        raise HTTPException(404, "Notebook not found")
    return nb


@router.post("")
async def create_notebook(body: NotebookCreate, db: Session = Depends(get_db),
                          claims: dict = Depends(claims_from_request)):
    user = await run_in_threadpool(upsert_user, db, claims)
    nb = Notebook(user_id=user.id, title=body.title.strip()[:120] or "Untitled")
    db.add(nb)
    db.commit()
    db.refresh(nb)
    return {"id": nb.id, "title": nb.title}


@router.get("")
async def list_notebooks(db: Session = Depends(get_db), claims: dict = Depends(claims_from_request)):
    user = await run_in_threadpool(upsert_user, db, claims)
    nbs = db.query(Notebook).filter(Notebook.user_id == user.id).order_by(Notebook.created_at.desc()).all()
    return [{"id": n.id, "title": n.title, "sources": len(n.sources)} for n in nbs]


@router.delete("/{notebook_id}")
async def delete_notebook(notebook_id: str, db: Session = Depends(get_db),
                          claims: dict = Depends(claims_from_request)):
    user = await run_in_threadpool(upsert_user, db, claims)
    nb = _owned_notebook(db, user.id, notebook_id)
    db.delete(nb)
    db.commit()
    return {"ok": True}


@router.post("/{notebook_id}/sources")
async def add_source(notebook_id: str, body: SourceCreate, db: Session = Depends(get_db),
                     claims: dict = Depends(claims_from_request)):
    user = await run_in_threadpool(upsert_user, db, claims)
    nb = _owned_notebook(db, user.id, notebook_id)
    if not body.text.strip():
        raise HTTPException(400, "Empty source text")
    src = Source(notebook_id=nb.id, title=body.title.strip()[:200],
                 content=body.text[: settings.max_source_chars])
    db.add(src)
    db.commit()
    db.refresh(src)
    return {"id": src.id, "title": src.title, "chars": len(src.content)}


@router.post("/{notebook_id}/sources/upload")
async def upload_source(notebook_id: str, db: Session = Depends(get_db),
                        claims: dict = Depends(claims_from_request),
                        file: UploadFile = File(...), title: str = Form("")):
    user = await run_in_threadpool(upsert_user, db, claims)
    nb = _owned_notebook(db, user.id, notebook_id)
    raw = await file.read()
    name = file.filename or "upload.txt"
    text = ""
    if name.lower().endswith(".pdf"):
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(raw))
            text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception as exc:
            raise HTTPException(400, f"PDF parse failed: {exc}")
    else:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1", errors="ignore")
    if not text.strip():
        raise HTTPException(400, "No extractable text found")
    src = Source(notebook_id=nb.id, title=(title or name)[:200],
                 content=text[: settings.max_source_chars])
    db.add(src)
    db.commit()
    db.refresh(src)
    return {"id": src.id, "title": src.title, "chars": len(src.content)}


@router.get("/{notebook_id}")
async def get_notebook(notebook_id: str, db: Session = Depends(get_db),
                       claims: dict = Depends(claims_from_request)):
    user = await run_in_threadpool(upsert_user, db, claims)
    nb = _owned_notebook(db, user.id, notebook_id)
    return {
        "id": nb.id, "title": nb.title,
        "sources": [{"id": s.id, "title": s.title, "chars": len(s.content)} for s in nb.sources],
    }


def _source_pairs(nb: Notebook) -> list[tuple[str, str]]:
    return [(s.title, s.content) for s in nb.sources]


def _require_sources(nb: Notebook):
    if not nb.sources:
        raise HTTPException(400, "Add at least one source first")


@router.post("/{notebook_id}/summarize")
async def summarize(notebook_id: str, db: Session = Depends(get_db),
                    claims: dict = Depends(claims_from_request)):
    user = await run_in_threadpool(upsert_user, db, claims)
    nb = _owned_notebook(db, user.id, notebook_id)
    _require_sources(nb)
    built = build_messages(
        instruction="Produce a structured study summary: heading, TL;DR (3 bullets), "
                    "key concepts with one-line explanations, and a 5-item revision checklist.",
        query="Summarize all material for exam preparation.",
        sources=_source_pairs(nb),
    )
    summary = await run_in_threadpool(llm.chat, built.messages)
    return {"summary": summary, "stats": built.stats}


@router.post("/{notebook_id}/chat")
async def notebook_chat(notebook_id: str, body: ChatBody, db: Session = Depends(get_db),
                        claims: dict = Depends(claims_from_request)):
    user = await run_in_threadpool(upsert_user, db, claims)
    nb = _owned_notebook(db, user.id, notebook_id)
    _require_sources(nb)
    built = build_messages(
        instruction="Answer the user's question about the study material. Explain step by step when useful.",
        query=body.message,
        sources=_source_pairs(nb),
    )
    answer = await run_in_threadpool(llm.chat, built.messages)
    return {"answer": answer, "stats": built.stats}


@router.post("/{notebook_id}/quiz")
async def generate_quiz(notebook_id: str, db: Session = Depends(get_db),
                        claims: dict = Depends(claims_from_request),
                        num_questions: int = 5):
    user = await run_in_threadpool(upsert_user, db, claims)
    nb = _owned_notebook(db, user.id, notebook_id)
    _require_sources(nb)
    num_questions = max(3, min(num_questions, 15))
    built = build_messages(
        instruction=f"Create a multiple-choice quiz with exactly {num_questions} questions "
                    "covering the most testable ideas. Return ONLY JSON matching: "
                    '{"questions":[{"question":"...","options":["a","b","c","d"],'
                    '"answer_index":0,"explanation":"why"}]}',
        query="Generate the quiz now.",
        sources=_source_pairs(nb),
        max_output_tokens=settings.max_output_tokens,
    )
    raw = await run_in_threadpool(llm.chat, built.messages, None, True)
    parsed = llm.parse_json(raw)
    questions = parsed.get("questions") or []
    cleaned = []
    for i, q in enumerate(questions):
        opts = [str(o) for o in (q.get("options") or [])][:5]
        ans = int(q.get("answer_index", 0))
        if len(opts) < 2 or not q.get("question"):
            continue
        cleaned.append({
            "question": str(q["question"])[:500],
            "options": opts,
            "answer_index": max(0, min(ans, len(opts) - 1)),
            "explanation": str(q.get("explanation", ""))[:800],
        })
    if not cleaned:
        raise HTTPException(502, "Model returned no usable questions; try again")
    quiz = Quiz(user_id=user.id, notebook_id=nb.id, data={"questions": cleaned})
    db.add(quiz)
    db.commit()
    db.refresh(quiz)
    public_qs = [{"index": i, "question": q["question"], "options": q["options"]}
                 for i, q in enumerate(cleaned)]
    return {"quiz_id": quiz.id, "questions": public_qs, "stats": built.stats}


@router.post("/quizzes/{quiz_id}/submit")
async def submit_quiz(quiz_id: str, body: QuizSubmit, db: Session = Depends(get_db),
                      claims: dict = Depends(claims_from_request)):
    user = await run_in_threadpool(upsert_user, db, claims)
    quiz = db.get(Quiz, quiz_id)
    if not quiz or quiz.user_id != user.id:
        raise HTTPException(404, "Quiz not found")
    questions = quiz.data.get("questions", [])
    score = 0
    review = []
    for i, q in enumerate(questions):
        given = body.answers[i] if i < len(body.answers) else -1
        correct = given == q["answer_index"]
        if correct:
            score += 1
        review.append({"index": i, "given": given, "correct": correct,
                       "answer_index": q["answer_index"], "explanation": q["explanation"]})
    max_score = len(questions)
    awarded_per = settings.quiz_points_per_correct
    result = award(db, user, score * awarded_per, f"quiz:{quiz_id}", ref=quiz.notebook_id or "")
    streak = touch_streak(db, user)
    attempt = QuizAttempt(quiz_id=quiz.id, user_id=user.id, score=score,
                          max_score=max_score, awarded=result["delta"])
    db.add(attempt)
    db.commit()
    return {"score": score, "max": max_score, "review": review,
            "points": result, "streak": streak}
