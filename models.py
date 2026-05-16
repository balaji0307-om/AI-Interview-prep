from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(24), default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (
        UniqueConstraint("topic", "mode", "question", name="uq_questions_topic_mode_question"),
        Index("ix_questions_topic_mode_sequence", "topic", "mode", "sequence"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    topic: Mapped[str] = mapped_column(String(32), index=True)
    mode: Mapped[str] = mapped_column(String(32), index=True)
    question: Mapped[str] = mapped_column(Text)
    sequence: Mapped[int] = mapped_column(Integer, index=True)
    difficulty: Mapped[str] = mapped_column(String(24), default="intermediate")
    source: Mapped[str] = mapped_column(String(64), default="question-bank-v3")
    solution: Mapped[str] = mapped_column(Text, default="")
    options: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    constraints: Mapped[str | None] = mapped_column(Text, nullable=True)
    sample_input: Mapped[str | None] = mapped_column(Text, nullable=True)
    sample_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_approach: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Attempt(Base):
    __tablename__ = "attempts"
    __table_args__ = (Index("ix_attempts_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    topic: Mapped[str] = mapped_column(String(32))
    mode: Mapped[str] = mapped_column(String(32))
    question: Mapped[str] = mapped_column(Text)
    question_id: Mapped[str] = mapped_column(String(64))
    submitted_answer: Mapped[str] = mapped_column(Text)
    is_correct: Mapped[bool] = mapped_column(default=False)
    feedback: Mapped[str] = mapped_column(Text, default="")
    solution: Mapped[str] = mapped_column(Text, default="")
    correct_answer: Mapped[str] = mapped_column(Text, default="")
    expected_approach: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ChatLog(Base):
    __tablename__ = "chat_logs"
    __table_args__ = (Index("ix_chat_logs_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    user_message: Mapped[str] = mapped_column(Text)
    assistant_message: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(String(32), default="local")
    related_suggestions: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
