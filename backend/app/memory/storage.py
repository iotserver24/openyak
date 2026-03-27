"""SQLite-backed memory storage for facts and context summaries."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.memory.models import MemoryContext, MemoryFact
from app.utils.id import generate_ulid

logger = logging.getLogger(__name__)


async def get_all_facts(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    min_confidence: float = 0.0,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Load all facts ordered by confidence (highest first)."""
    async with session_factory() as db:
        async with db.begin():
            stmt = (
                select(MemoryFact)
                .where(MemoryFact.confidence >= min_confidence)
                .order_by(MemoryFact.confidence.desc())
                .limit(limit)
            )
            rows = (await db.execute(stmt)).scalars().all()
            return [
                {
                    "id": r.id,
                    "content": r.content,
                    "category": r.category,
                    "confidence": r.confidence,
                    "source_session_id": r.source_session_id,
                    "time_created": r.time_created.isoformat() if r.time_created else None,
                }
                for r in rows
            ]


async def get_all_contexts(
    session_factory: async_sessionmaker[AsyncSession],
) -> dict[str, str]:
    """Load all context summaries as {section: summary}."""
    async with session_factory() as db:
        async with db.begin():
            rows = (await db.execute(select(MemoryContext))).scalars().all()
            return {r.section: r.summary for r in rows}


async def add_facts(
    session_factory: async_sessionmaker[AsyncSession],
    facts: list[dict[str, Any]],
    *,
    source_session_id: str | None = None,
    max_facts: int = 100,
) -> int:
    """Add new facts, deduplicating by normalized content. Returns count added."""
    if not facts:
        return 0

    async with session_factory() as db:
        async with db.begin():
            # Load existing for dedup
            existing = (await db.execute(select(MemoryFact.content))).scalars().all()
            existing_normalized = {_normalize(c) for c in existing}

            added = 0
            for f in facts:
                content = (f.get("content") or "").strip()
                if not content:
                    continue
                if _normalize(content) in existing_normalized:
                    continue

                confidence = f.get("confidence", 0.8)
                if not isinstance(confidence, (int, float)) or confidence != confidence:
                    confidence = 0.8
                confidence = max(0.0, min(1.0, float(confidence)))

                db.add(MemoryFact(
                    id=generate_ulid(),
                    content=content,
                    category=f.get("category", "context"),
                    confidence=confidence,
                    source_session_id=source_session_id,
                ))
                existing_normalized.add(_normalize(content))
                added += 1

            # Enforce max_facts: keep highest-confidence facts
            total_stmt = select(MemoryFact.id).order_by(MemoryFact.confidence.desc())
            all_ids = (await db.execute(total_stmt)).scalars().all()
            if len(all_ids) > max_facts:
                ids_to_remove = all_ids[max_facts:]
                await db.execute(
                    delete(MemoryFact).where(MemoryFact.id.in_(ids_to_remove))
                )
                logger.info(
                    "Pruned %d low-confidence facts (limit=%d)",
                    len(ids_to_remove), max_facts,
                )

    return added


async def remove_facts(
    session_factory: async_sessionmaker[AsyncSession],
    fact_ids: list[str],
) -> int:
    """Remove facts by ID. Returns count removed."""
    if not fact_ids:
        return 0
    async with session_factory() as db:
        async with db.begin():
            result = await db.execute(
                delete(MemoryFact).where(MemoryFact.id.in_(fact_ids))
            )
            return result.rowcount


async def upsert_context(
    session_factory: async_sessionmaker[AsyncSession],
    section: str,
    summary: str,
) -> None:
    """Update or insert a context summary section."""
    async with session_factory() as db:
        async with db.begin():
            existing = await db.execute(
                select(MemoryContext).where(MemoryContext.section == section)
            )
            row = existing.scalar_one_or_none()
            if row:
                row.summary = summary
            else:
                db.add(MemoryContext(
                    id=generate_ulid(),
                    section=section,
                    summary=summary,
                ))


async def update_fact(
    session_factory: async_sessionmaker[AsyncSession],
    fact_id: str,
    *,
    content: str | None = None,
    category: str | None = None,
    confidence: float | None = None,
) -> bool:
    """Update an existing fact. Only updates non-None fields. Returns True if found."""
    async with session_factory() as db:
        async with db.begin():
            row = await db.get(MemoryFact, fact_id)
            if not row:
                return False
            if content is not None:
                row.content = content
            if category is not None:
                row.category = category
            if confidence is not None:
                row.confidence = max(0.0, min(1.0, float(confidence)))
            return True


async def clear_all(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Delete all memory data."""
    async with session_factory() as db:
        async with db.begin():
            await db.execute(delete(MemoryFact))
            await db.execute(delete(MemoryContext))


def _normalize(text: str) -> str:
    """Normalize text for deduplication (lowercase, collapse whitespace)."""
    return " ".join(text.lower().split())
