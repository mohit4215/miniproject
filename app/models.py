import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from .db import Base


def new_id() -> str:
    return uuid.uuid4().hex


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True)
    email = Column(String, default="")
    display_name = Column(String, default="")
    photo_url = Column(String, default="")
    is_admin = Column(Boolean, default=False)
    points = Column(Integer, default=0, index=True)
    current_streak = Column(Integer, default=0)
    longest_streak = Column(Integer, default=0)
    last_active = Column(Date, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Room(Base):
    __tablename__ = "rooms"

    id = Column(String, primary_key=True, default=new_id)
    code = Column(String(8), unique=True, index=True)
    name = Column(String, nullable=False)
    host_id = Column(String, index=True)
    is_public = Column(Boolean, default=True)
    duration_default = Column(Integer, default=25)
    created_at = Column(DateTime, default=datetime.utcnow)


class RoomMember(Base):
    __tablename__ = "room_members"

    room_id = Column(String, ForeignKey("rooms.id"), primary_key=True)
    user_id = Column(String, primary_key=True)
    joined_at = Column(DateTime, default=datetime.utcnow)


class FocusSession(Base):
    __tablename__ = "focus_sessions"

    id = Column(String, primary_key=True, default=new_id)
    room_id = Column(String, index=True)
    started_by = Column(String)
    duration_min = Column(Integer)
    started_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime)
    status = Column(String, default="running")


class Violation(Base):
    __tablename__ = "violations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, index=True)
    user_id = Column(String, index=True)
    kind = Column(String)
    at = Column(DateTime, default=datetime.utcnow)


class Notebook(Base):
    __tablename__ = "notebooks"

    id = Column(String, primary_key=True, default=new_id)
    user_id = Column(String, index=True)
    title = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    sources = relationship("Source", cascade="all,delete-orphan", backref="notebook")


class Source(Base):
    __tablename__ = "sources"

    id = Column(String, primary_key=True, default=new_id)
    notebook_id = Column(String, ForeignKey("notebooks.id"), index=True)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Quiz(Base):
    __tablename__ = "quizzes"

    id = Column(String, primary_key=True, default=new_id)
    user_id = Column(String, index=True)
    notebook_id = Column(String, index=True)
    data = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"

    id = Column(String, primary_key=True, default=new_id)
    quiz_id = Column(String, ForeignKey("quizzes.id"), index=True)
    user_id = Column(String, index=True)
    score = Column(Integer)
    max_score = Column(Integer)
    awarded = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)


class Note(Base):
    __tablename__ = "notes"

    id = Column(String, primary_key=True, default=new_id)
    user_id = Column(String, index=True)
    title = Column(String, nullable=False)
    content = Column(Text, default="")
    tags = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class PointEvent(Base):
    __tablename__ = "point_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, index=True)
    delta = Column(Integer)
    reason = Column(String)
    ref = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
