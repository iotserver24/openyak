"""Debounced async queue for memory updates.

Collects conversation contexts and processes them in batches to minimize
LLM calls. Uses a timer-based debounce: each new addition resets the timer.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.memory.config import get_memory_config
from app.memory.storage import add_facts, get_all_contexts, get_all_facts, remove_facts, upsert_context
from app.memory.updater import (
    MEMORY_UPDATE_PROMPT,
    format_conversation_for_update,
    format_current_memory,
    parse_update_response,
)

logger = logging.getLogger(__name__)


@dataclass
class ConversationContext:
    """A conversation snapshot queued for memory extraction."""

    session_id: str
    messages: list[dict[str, Any]]
    model_id: str | None = None
    timestamp: float = field(default_factory=lambda: __import__("time").time())


class MemoryUpdateQueue:
    """Debounced queue that batches conversation contexts for memory extraction.

    Usage::

        queue = MemoryUpdateQueue(session_factory, provider_registry)
        queue.add(session_id, llm_messages)  # Resets debounce timer
        # ... after debounce_seconds, extraction runs automatically
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        provider_registry: Any,
    ) -> None:
        self._session_factory = session_factory
        self._provider_registry = provider_registry
        self._pending: dict[str, ConversationContext] = {}
        self._timer: asyncio.TimerHandle | None = None
        self._processing = False
        self._lock = asyncio.Lock()

    def add(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        *,
        model_id: str | None = None,
    ) -> None:
        """Queue a conversation for memory extraction.

        Newer submissions for the same session_id replace older ones.
        Resets the debounce timer.

        Args:
            model_id: Use the caller's current model/provider instead of
                      auto-selecting a cheap model.
        """
        config = get_memory_config()
        if not config.enabled:
            return

        self._pending[session_id] = ConversationContext(
            session_id=session_id,
            messages=messages,
            model_id=model_id,
        )

        # Reset debounce timer
        if self._timer is not None:
            self._timer.cancel()

        loop = asyncio.get_event_loop()
        self._timer = loop.call_later(
            config.debounce_seconds,
            lambda: asyncio.ensure_future(self._process()),
        )
        logger.info(
            "Memory queue: added session %s, will process in %ds (pending: %d)",
            session_id, config.debounce_seconds, len(self._pending),
        )

    async def _process(self) -> None:
        """Process all pending conversations for memory extraction."""
        async with self._lock:
            if self._processing:
                logger.info("Memory queue: already processing, skipping")
                return
            self._processing = True

        try:
            # Snapshot and clear pending
            to_process = dict(self._pending)
            self._pending.clear()

            if not to_process:
                logger.info("Memory queue: nothing to process")
                return

            logger.info("Memory queue: processing %d session(s)", len(to_process))
            config = get_memory_config()

            for session_id, ctx in to_process.items():
                try:
                    await self._extract_memory(ctx, config)
                except Exception:
                    logger.exception(
                        "Memory extraction failed for session %s", session_id
                    )
                # Small delay between extractions to avoid rate limiting
                await asyncio.sleep(0.5)

        finally:
            async with self._lock:
                self._processing = False

    async def _extract_memory(
        self,
        ctx: ConversationContext,
        config: Any,
    ) -> None:
        """Run LLM memory extraction for a single conversation."""
        # Format conversation
        conversation_text = format_conversation_for_update(ctx.messages)
        if not conversation_text.strip():
            return

        # Load current memory state
        contexts = await get_all_contexts(self._session_factory)
        facts = await get_all_facts(
            self._session_factory,
            min_confidence=config.fact_confidence_threshold,
        )
        current_memory = format_current_memory(contexts, facts)

        # Build the extraction prompt
        prompt = MEMORY_UPDATE_PROMPT.format(
            current_memory=current_memory,
            conversation=conversation_text,
        )

        # Call LLM for extraction (use caller's model when provided)
        response_text = await self._call_llm(prompt, model_id=ctx.model_id)
        if not response_text:
            return

        # Parse and apply updates
        updates = parse_update_response(response_text)
        if not updates:
            return

        # Apply context updates
        update_contexts = updates.get("contexts", {})
        for section, data in update_contexts.items():
            if isinstance(data, dict) and data.get("should_update"):
                summary = data.get("summary", "").strip()
                if summary:
                    await upsert_context(self._session_factory, section, summary)

        # Add new facts
        new_facts = updates.get("new_facts", [])
        if new_facts:
            added = await add_facts(
                self._session_factory,
                new_facts,
                source_session_id=ctx.session_id,
                max_facts=config.max_facts,
            )
            if added:
                logger.info("Memory: added %d new fact(s) from session %s", added, ctx.session_id)

        # Remove outdated facts
        to_remove = updates.get("facts_to_remove", [])
        if to_remove:
            removed = await remove_facts(self._session_factory, to_remove)
            if removed:
                logger.info("Memory: removed %d outdated fact(s)", removed)

    async def _call_llm(
        self, prompt: str, *, model_id: str | None = None
    ) -> str | None:
        """Call an LLM to extract memory from a conversation.

        Uses the caller's *model_id* (i.e. the user's current model/provider)
        so that memory extraction stays on the same provider the session is
        already using.  Falls back to any available model only when no
        explicit model_id is given.
        """
        try:
            effective_model_id = model_id

            # Fallback: pick any available model
            if not effective_model_id:
                all_models = self._provider_registry.all_models()
                if all_models:
                    effective_model_id = all_models[0].id

            if not effective_model_id:
                logger.warning("Memory: no model available for extraction")
                return None

            resolved = self._provider_registry.resolve_model(effective_model_id)
            if not resolved:
                return None

            provider, _model_info = resolved

            # Simple non-streaming call with system prompt
            # The system instruction is required by some providers (e.g. ChatGPT Subscription)
            system = "You are a memory extraction system. Extract structured facts and context from conversations. Always respond with valid JSON only."
            messages = [{"role": "user", "content": prompt}]
            response_text = ""
            async for chunk in provider.stream_chat(
                effective_model_id, messages, system=system, max_tokens=2000
            ):
                if chunk.type == "text-delta":
                    response_text += chunk.data.get("text", "")

            return response_text if response_text.strip() else None

        except Exception:
            logger.exception("Memory: LLM call failed for extraction")
            return None

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    @property
    def is_processing(self) -> bool:
        return self._processing

    def clear(self) -> None:
        """Clear pending queue without processing."""
        self._pending.clear()
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None


# Module-level singleton (initialized by app lifespan)
_queue: MemoryUpdateQueue | None = None


def get_memory_queue() -> MemoryUpdateQueue | None:
    return _queue


def set_memory_queue(queue: MemoryUpdateQueue) -> None:
    global _queue
    _queue = queue
