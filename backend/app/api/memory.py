"""API endpoints for long-term memory management."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, get_session_factory

router = APIRouter(prefix="/memory")


class FactResponse(BaseModel):
    id: str
    content: str
    category: str
    confidence: float
    source_session_id: str | None = None
    time_created: str | None = None


class MemoryResponse(BaseModel):
    contexts: dict[str, str]
    facts: list[FactResponse]


class AddFactRequest(BaseModel):
    content: str = Field(min_length=1, max_length=1000)
    category: str = Field(default="context", pattern="^(preference|knowledge|context|behavior|goal)$")
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)


class UpdateContextRequest(BaseModel):
    section: str = Field(pattern="^(work_context|personal_context|top_of_mind)$")
    summary: str = Field(max_length=2000)


class RemoveFactsRequest(BaseModel):
    fact_ids: list[str]


class MemoryConfigResponse(BaseModel):
    enabled: bool
    injection_enabled: bool


class MemoryConfigUpdate(BaseModel):
    enabled: bool | None = None
    injection_enabled: bool | None = None


@router.get("", response_model=MemoryResponse)
async def get_memory(session_factory=Depends(get_session_factory)):
    """Get all stored memory (contexts + facts)."""
    from app.memory.storage import get_all_contexts, get_all_facts

    contexts = await get_all_contexts(session_factory)
    facts = await get_all_facts(session_factory)
    return MemoryResponse(
        contexts=contexts,
        facts=[FactResponse(**f) for f in facts],
    )


@router.post("/facts", response_model=dict)
async def add_fact(
    request: AddFactRequest,
    session_factory=Depends(get_session_factory),
):
    """Manually add a memory fact."""
    from app.memory.storage import add_facts

    added = await add_facts(
        session_factory,
        [{"content": request.content, "category": request.category, "confidence": request.confidence}],
    )
    return {"added": added}


@router.put("/contexts", response_model=dict)
async def update_context(
    request: UpdateContextRequest,
    session_factory=Depends(get_session_factory),
):
    """Update a context summary section."""
    from app.memory.storage import upsert_context

    await upsert_context(session_factory, request.section, request.summary)
    return {"status": "ok"}


@router.delete("/facts", response_model=dict)
async def remove_facts_endpoint(
    request: RemoveFactsRequest,
    session_factory=Depends(get_session_factory),
):
    """Remove specific facts by ID."""
    from app.memory.storage import remove_facts

    removed = await remove_facts(session_factory, request.fact_ids)
    return {"removed": removed}


@router.get("/config", response_model=MemoryConfigResponse)
async def get_config():
    """Get memory system configuration."""
    from app.memory.config import get_memory_config

    cfg = get_memory_config()
    return MemoryConfigResponse(enabled=cfg.enabled, injection_enabled=cfg.injection_enabled)


@router.patch("/config", response_model=MemoryConfigResponse)
async def update_config(request: MemoryConfigUpdate):
    """Update memory system configuration."""
    from app.memory.config import get_memory_config, set_memory_config

    cfg = get_memory_config()
    data = cfg.model_dump()
    if request.enabled is not None:
        data["enabled"] = request.enabled
    if request.injection_enabled is not None:
        data["injection_enabled"] = request.injection_enabled
    from app.memory.config import MemoryConfig
    new_cfg = MemoryConfig(**data)
    set_memory_config(new_cfg)
    return MemoryConfigResponse(enabled=new_cfg.enabled, injection_enabled=new_cfg.injection_enabled)


@router.delete("", response_model=dict)
async def clear_memory(session_factory=Depends(get_session_factory)):
    """Clear all memory data."""
    from app.memory.storage import clear_all

    await clear_all(session_factory)
    return {"status": "cleared"}
