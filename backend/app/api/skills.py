"""Skill listing and toggle endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

router = APIRouter()


def _skill_source(skill_name: str, location: str, request: Request) -> str:
    """Determine the source of a skill: 'plugin', 'bundled', or 'project'."""
    if ":" in skill_name:
        return "plugin"
    # Check if location is under the bundled data directory
    if "/data/skills/" in location or "\\data\\skills\\" in location:
        return "bundled"
    return "project"


def _skill_to_dict(skill, registry, request: Request) -> dict[str, Any]:
    """Convert a SkillInfo to an API response dict."""
    return {
        "name": skill.name,
        "description": skill.description,
        "location": skill.location,
        "source": _skill_source(skill.name, skill.location, request),
        "enabled": not registry.is_disabled(skill.name),
    }


@router.get("/skills")
async def list_skills(request: Request) -> list[dict[str, Any]]:
    """List all discovered skills."""
    registry = request.app.state.skill_registry
    return [_skill_to_dict(skill, registry, request) for skill in registry.all_skills()]


@router.get("/skills/{skill_name}")
async def get_skill(request: Request, skill_name: str) -> dict[str, Any]:
    """Get skill details including full content."""
    registry = request.app.state.skill_registry
    skill = registry.get(skill_name)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_name}")
    return {
        "name": skill.name,
        "description": skill.description,
        "location": skill.location,
        "content": skill.content,
    }


@router.post("/skills/{skill_name}/enable")
async def enable_skill(skill_name: str, request: Request) -> dict[str, Any]:
    """Enable a disabled skill."""
    registry = request.app.state.skill_registry
    skill = registry.get(skill_name)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_name}")
    registry.enable(skill_name)
    return {
        "success": True,
        "skills": [_skill_to_dict(s, registry, request) for s in registry.all_skills()],
    }


@router.post("/skills/{skill_name}/disable")
async def disable_skill(skill_name: str, request: Request) -> dict[str, Any]:
    """Disable a skill (excludes it from LLM available skills)."""
    registry = request.app.state.skill_registry
    skill = registry.get(skill_name)
    if skill is None:
        raise HTTPException(status_code=404, detail=f"Skill not found: {skill_name}")
    registry.disable(skill_name)
    return {
        "success": True,
        "skills": [_skill_to_dict(s, registry, request) for s in registry.all_skills()],
    }
