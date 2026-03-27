"""SQLAlchemy model for long-term memory facts."""

from __future__ import annotations

from sqlalchemy import Float, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.utils.id import generate_ulid


class MemoryFact(Base, TimestampMixin):
    """A single fact extracted from a conversation.

    Facts are confidence-scored and categorized for efficient retrieval
    and system prompt injection.
    """

    __tablename__ = "memory_fact"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_ulid)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(
        String(32), nullable=False, default="context"
    )  # preference | knowledge | context | behavior | goal
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.8)
    source_session_id: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("ix_memory_fact_category", "category"),
        Index("ix_memory_fact_confidence", "confidence"),
    )


class MemoryContext(Base, TimestampMixin):
    """Structured context summaries (work, personal, top-of-mind).

    Each row is a named context section with a summary string.
    Only one row per section name is kept (upsert pattern).
    """

    __tablename__ = "memory_context"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_ulid)
    section: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True
    )  # work_context | personal_context | top_of_mind
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
