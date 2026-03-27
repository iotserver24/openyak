"""Memory system configuration."""

from __future__ import annotations

from pydantic import BaseModel, Field


class MemoryConfig(BaseModel):
    """Configuration for the long-term memory system."""

    enabled: bool = True
    debounce_seconds: int = Field(default=30, ge=5, le=300)
    max_facts: int = Field(default=100, ge=10, le=500)
    fact_confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    injection_enabled: bool = True
    max_injection_tokens: int = Field(default=1500, ge=100, le=8000)


# Module-level default config
_config = MemoryConfig()


def get_memory_config() -> MemoryConfig:
    return _config


def set_memory_config(config: MemoryConfig) -> None:
    global _config
    _config = config
