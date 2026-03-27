"""Middleware: queue conversations for async memory extraction.

After the agent completes a generation, this middleware queues the
conversation for background memory extraction via the MemoryUpdateQueue.
"""

from __future__ import annotations

from typing import Any

from app.session.middleware import Middleware, MiddlewareContext


class MemoryMiddleware(Middleware):
    """Queues completed conversations for memory extraction."""

    async def on_step_complete(self, ctx: MiddlewareContext) -> None:
        try:
            from app.memory.queue import get_memory_queue

            queue = get_memory_queue()
            if queue is None:
                return

            # The actual message loading and queueing is deferred to
            # post-loop in SessionPrompt._post_loop() since we need
            # the full conversation, not just this step.
            # This hook is a placeholder for future per-step extraction.
        except Exception:
            pass
