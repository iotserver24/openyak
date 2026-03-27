"""Memory injection into system prompts.

Formats stored memory (contexts + facts) into a compact section that
gets appended to the system prompt, giving the LLM awareness of the
user's history and preferences.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.memory.config import get_memory_config
from app.memory.storage import get_all_contexts, get_all_facts

logger = logging.getLogger(__name__)


async def build_memory_section(
    session_factory: async_sessionmaker[AsyncSession],
) -> str | None:
    """Build a memory section for the system prompt.

    Returns a formatted string or None if memory is empty/disabled.
    """
    config = get_memory_config()
    if not config.enabled or not config.injection_enabled:
        return None

    contexts = await get_all_contexts(session_factory)
    facts = await get_all_facts(
        session_factory,
        min_confidence=config.fact_confidence_threshold,
        limit=config.max_facts,
    )

    if not any(contexts.values()) and not facts:
        return None

    return _format_memory(contexts, facts, max_tokens=config.max_injection_tokens)


def _format_memory(
    contexts: dict[str, str],
    facts: list[dict[str, Any]],
    *,
    max_tokens: int = 1500,
) -> str:
    """Format memory into a system prompt section.

    Stays within the token budget by including highest-confidence facts
    first and truncating when the budget is exhausted.
    """
    parts = ["# Memory\nInformation remembered from previous conversations:\n"]

    # Context summaries
    section_labels = {
        "work_context": "Work",
        "personal_context": "Personal",
        "top_of_mind": "Current Focus",
    }
    context_lines = []
    for section, label in section_labels.items():
        summary = contexts.get(section, "").strip()
        if summary:
            context_lines.append(f"- **{label}**: {summary}")

    if context_lines:
        parts.append("## User Context")
        parts.extend(context_lines)
        parts.append("")

    # Facts (sorted by confidence, highest first — already sorted by storage)
    if facts:
        parts.append("## Known Facts")
        for f in facts:
            cat = f.get("category", "context")
            conf = f.get("confidence", 0.0)
            content = f.get("content", "")
            parts.append(f"- [{cat}] {content}")

    parts.append("")
    parts.append("When the user asks you to remember or forget something, use the memory tool to save or remove facts.")

    text = "\n".join(parts)

    # Rough token budget enforcement (1 token ≈ 4 chars for English, ~2 for CJK)
    char_budget = max_tokens * 3
    if len(text) > char_budget:
        text = text[:char_budget] + "\n..."

    return text
