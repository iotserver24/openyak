"""OpenAI-compatible API endpoints for external integrations (e.g. OpenClaw).

Exposes /v1/chat/completions and /v1/models so OpenYak can be used as a
drop-in OpenAI-compatible backend. Internally delegates to the same
run_generation() pipeline used by the native chat API.
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.schemas.chat import PromptRequest
from app.session.manager import create_session, get_session
from app.session.processor import run_generation
from app.streaming.events import (
    AGENT_ERROR,
    DONE,
    PERMISSION_REQUEST,
    QUESTION,
    TEXT_DELTA,
    TOOL_START,
    TOOL_RESULT,
    SSEEvent,
)
from app.streaming.manager import GenerationJob, StreamManager
from app.utils.id import generate_ulid

logger = logging.getLogger(__name__)

router = APIRouter()

# Heartbeat interval — keeps the SSE connection alive through proxies.
_HEARTBEAT_INTERVAL = 15.0

# Agent name prefix used in model IDs: "openyak-build" -> agent "build"
_MODEL_PREFIX = "openyak-"

# Available agents exposed as model IDs.
_AGENT_MODELS = {
    "openyak-build": {"agent": "build", "description": "Full-featured assistant with all tools"},
    "openyak-plan": {"agent": "plan", "description": "Read-only analysis and planning"},
    "openyak-explore": {"agent": "explore", "description": "Fast search and exploration"},
    "openyak-general": {"agent": "general", "description": "General-purpose assistant"},
}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: str = "user"
    content: Any = ""
    name: str | None = None


class ChatCompletionRequest(BaseModel):
    model: str = "openyak-build"
    messages: list[ChatMessage] = Field(default_factory=list)
    stream: bool = False
    user: str | None = None  # Channel user key for session mapping
    temperature: float | None = None
    max_tokens: int | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_stream_manager(request: Request) -> StreamManager:
    if not hasattr(request.app.state, "stream_manager"):
        request.app.state.stream_manager = StreamManager()
    return request.app.state.stream_manager


def _resolve_agent(model: str) -> str:
    """Map model ID to agent name. Falls back to 'build'."""
    if model in _AGENT_MODELS:
        return _AGENT_MODELS[model]["agent"]
    if model.startswith(_MODEL_PREFIX):
        return model[len(_MODEL_PREFIX):]
    return "build"


def _resolve_default_model(request: Request) -> str | None:
    """Pick the best model for external API calls (e.g. from OpenClaw).

    Priority: subscription > Anthropic > paid OpenRouter > free.
    """
    registry = getattr(request.app.state, "provider_registry", None)
    if registry is None:
        return None
    all_models = registry.all_models()
    if not all_models:
        return None

    # 1. Subscription models (ChatGPT subscription)
    sub = [m for m in all_models if m.provider_id == "openai-subscription"]
    if sub:
        return sub[0].id

    # 2. Anthropic
    anth = [m for m in all_models if m.provider_id == "anthropic"]
    if anth:
        return anth[0].id

    # 3. Paid models
    paid = [m for m in all_models if m.pricing and (m.pricing.prompt > 0 or m.pricing.completion > 0)]
    if paid:
        return paid[0].id

    return all_models[0].id


def _extract_prompt(messages: list[ChatMessage]) -> tuple[str, str | None]:
    """Extract prompt text and optional system context from OpenAI messages.

    Returns (user_text, system_text).
    """
    system_parts: list[str] = []
    user_text = ""

    for msg in messages:
        content = msg.content if isinstance(msg.content, str) else _content_to_text(msg.content)
        if msg.role == "system":
            system_parts.append(content)
        elif msg.role == "user":
            user_text = content  # Last user message wins

    system_text = "\n\n".join(system_parts) if system_parts else None
    return user_text, system_text


def _content_to_text(content: Any) -> str:
    """Convert OpenAI multimodal content array to plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text":
                    parts.append(part.get("text", ""))
                elif part.get("type") == "input_text":
                    parts.append(part.get("text", ""))
        return "\n".join(parts)
    return str(content) if content else ""


def _on_task_done(task: asyncio.Task[None], *, job: GenerationJob) -> None:
    """Log unhandled exceptions from generation tasks."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error("OpenAI-compat generation failed %s: %s", task.get_name(), exc, exc_info=exc)
        try:
            job.publish(SSEEvent(AGENT_ERROR, {"error_message": "Internal error."}))
        except Exception:
            pass


async def _run_with_semaphore(sm: StreamManager, job: GenerationJob, coro) -> None:
    try:
        await asyncio.wait_for(sm._semaphore.acquire(), timeout=30)
    except asyncio.TimeoutError:
        job.publish(SSEEvent(AGENT_ERROR, {"error_message": "Server busy."}))
        job.complete()
        return
    try:
        await coro
    finally:
        sm._semaphore.release()


async def _get_or_create_session(request: Request, channel_user_key: str) -> str:
    """Find existing session for a channel user or create a new one.

    Uses a simple lookup: search sessions whose slug matches the channel key.
    The slug field is repurposed as a stable channel identifier.
    """
    session_factory = request.app.state.session_factory
    async with session_factory() as db:
        from sqlalchemy import select
        from app.models.session import Session

        stmt = (
            select(Session)
            .where(Session.slug == channel_user_key, Session.parent_id.is_(None))
            .order_by(Session.time_created.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        session = result.scalar_one_or_none()

        if session:
            return session.id

        # Create new session tagged with the channel user key
        new_session = await create_session(
            db,
            title=f"Channel: {channel_user_key}",
        )
        new_session.slug = channel_user_key
        await db.commit()
        return new_session.id


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/v1/models")
async def list_models():
    """List available models (agents)."""
    models = []
    for model_id, info in _AGENT_MODELS.items():
        models.append({
            "id": model_id,
            "object": "model",
            "created": 1700000000,
            "owned_by": "openyak",
            "description": info["description"],
        })
    return {"object": "list", "data": models}


@router.post("/v1/chat/completions")
async def chat_completions(request: Request, body: ChatCompletionRequest):
    """OpenAI-compatible chat completions endpoint.

    Delegates to OpenYak's full agent loop (run_generation) and translates
    SSE events into the OpenAI streaming format.
    """
    sm = _get_stream_manager(request)

    # Resolve session
    if body.user:
        session_id = await _get_or_create_session(request, body.user)
    else:
        session_id = generate_ulid()

    stream_id = generate_ulid()
    agent = _resolve_agent(body.model)
    user_text, _system_text = _extract_prompt(body.messages)

    if not user_text:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "No user message found in messages array.", "type": "invalid_request_error"}},
        )

    # Create generation job
    job = sm.create_job(stream_id=stream_id, session_id=session_id)
    # Non-interactive: permissions auto-approve in headless mode
    job.interactive = False

    # Use the user's best model (subscription > anthropic > paid > free)
    model_id = _resolve_default_model(request)
    logger.info("OpenAI-compat: agent=%s, model=%s", agent, model_id)

    prompt_request = PromptRequest(
        session_id=session_id,
        text=user_text,
        agent=agent,
        model=model_id,
    )

    coro = run_generation(
        job,
        prompt_request,
        session_factory=request.app.state.session_factory,
        provider_registry=request.app.state.provider_registry,
        agent_registry=request.app.state.agent_registry,
        tool_registry=request.app.state.tool_registry,
        index_manager=getattr(request.app.state, "index_manager", None),
    )
    task = asyncio.create_task(
        _run_with_semaphore(sm, job, coro),
        name=f"gen-oai-{stream_id}",
    )
    task.add_done_callback(functools.partial(_on_task_done, job=job))
    job.task = task

    if body.stream:
        return StreamingResponse(
            _stream_openai_chunks(job, body.model, stream_id),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        return await _collect_response(job, body.model, stream_id)


async def _stream_openai_chunks(
    job: GenerationJob,
    model: str,
    run_id: str,
):
    """Translate OpenYak SSE events into OpenAI streaming chunks."""
    queue = job.subscribe()
    created = int(time.time())

    # Initial role chunk
    yield _sse({"id": run_id, "object": "chat.completion.chunk", "created": created, "model": model,
                "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]})

    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_INTERVAL)
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"
                continue

            if event is None:
                break

            if event.event == TEXT_DELTA:
                text = event.data.get("text", "")
                if text:
                    yield _sse({"id": run_id, "object": "chat.completion.chunk", "created": created, "model": model,
                                "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]})

            elif event.event == DONE:
                yield _sse({"id": run_id, "object": "chat.completion.chunk", "created": created, "model": model,
                            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
                yield "data: [DONE]\n\n"
                break

            elif event.event == AGENT_ERROR:
                error_msg = event.data.get("error_message", "Unknown error")
                # Send error as content then stop
                yield _sse({"id": run_id, "object": "chat.completion.chunk", "created": created, "model": model,
                            "choices": [{"index": 0, "delta": {"content": f"\n[Error: {error_msg}]"}, "finish_reason": None}]})
                yield _sse({"id": run_id, "object": "chat.completion.chunk", "created": created, "model": model,
                            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
                yield "data: [DONE]\n\n"
                break

            # tool-call, tool-result, permission-request, etc. are silent — internal to OpenYak

    except asyncio.CancelledError:
        pass


async def _collect_response(
    job: GenerationJob,
    model: str,
    run_id: str,
) -> JSONResponse:
    """Collect all text-delta events and return a single chat completion response."""
    queue = job.subscribe()
    text_parts: list[str] = []
    error_msg: str | None = None

    while True:
        try:
            event = await asyncio.wait_for(queue.get(), timeout=300)
        except asyncio.TimeoutError:
            error_msg = "Generation timed out."
            break

        if event is None:
            break

        if event.event == TEXT_DELTA:
            text_parts.append(event.data.get("text", ""))
        elif event.event == DONE:
            break
        elif event.event == AGENT_ERROR:
            error_msg = event.data.get("error_message", "Unknown error")
            break

    content = "".join(text_parts)
    if error_msg and not content:
        content = f"[Error: {error_msg}]"

    return JSONResponse({
        "id": run_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    })


def _sse(data: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(data)}\n\n"
