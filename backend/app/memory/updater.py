"""LLM-based memory extraction from conversations.

Analyzes conversation messages and extracts structured facts, context
summaries, and user preferences for long-term storage.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

MEMORY_UPDATE_PROMPT = """\
You are a memory extraction system. Analyze the conversation below and extract:

1. **Context summaries** — brief summaries about the user:
   - work_context: Their role, current projects, tech stack (1-3 sentences)
   - personal_context: Personal preferences, communication style (1-2 sentences)
   - top_of_mind: What they're currently focused on (2-3 sentences)

2. **New facts** — discrete pieces of information worth remembering:
   - Each fact should be a single, self-contained statement
   - Assign a category: preference, knowledge, context, behavior, or goal
   - Assign a confidence score (0.0-1.0):
     - 0.9-1.0: Explicitly stated by the user
     - 0.7-0.8: Strongly implied from their actions/requests
     - 0.5-0.6: Inferred patterns (use sparingly)

3. **Facts to remove** — IDs of existing facts that are now outdated or wrong.

Rules:
- Do NOT extract file paths, temporary states, or debugging details.
- Do NOT extract facts about the conversation itself (e.g., "user asked about X").
- Focus on durable information that will be useful in FUTURE conversations.
- If the conversation has nothing worth remembering, return empty arrays.

Current memory state:
{current_memory}

Conversation:
{conversation}

Respond with ONLY valid JSON (no markdown, no explanation):
{{
  "contexts": {{
    "work_context": {{"summary": "...", "should_update": true/false}},
    "personal_context": {{"summary": "...", "should_update": true/false}},
    "top_of_mind": {{"summary": "...", "should_update": true/false}}
  }},
  "new_facts": [
    {{"content": "...", "category": "...", "confidence": 0.0-1.0}}
  ],
  "facts_to_remove": ["fact_id_1"]
}}"""


def format_conversation_for_update(messages: list[dict[str, Any]]) -> str:
    """Format LLM message history into a compact string for memory extraction.

    Only includes user and final assistant text — strips tool calls and
    intermediate results to focus on meaningful content.
    """
    lines = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")

        if role == "user" and isinstance(content, str) and content.strip():
            lines.append(f"User: {content.strip()[:2000]}")
        elif role == "assistant" and isinstance(content, str) and content.strip():
            lines.append(f"Assistant: {content.strip()[:2000]}")
        # Skip tool messages — they're noise for memory extraction

    return "\n\n".join(lines)


def format_current_memory(
    contexts: dict[str, str],
    facts: list[dict[str, Any]],
) -> str:
    """Format existing memory state for the extraction prompt."""
    parts = []

    if any(contexts.values()):
        parts.append("## Context Summaries")
        for section, summary in contexts.items():
            if summary:
                parts.append(f"- {section}: {summary}")

    if facts:
        parts.append("\n## Existing Facts")
        for f in facts[:50]:  # Limit to avoid prompt bloat
            parts.append(
                f"- [{f['id']}] [{f['category']} | {f['confidence']:.1f}] {f['content']}"
            )

    return "\n".join(parts) if parts else "(empty — no prior memory)"


def parse_update_response(response_text: str) -> dict[str, Any] | None:
    """Parse the LLM's JSON response for memory updates.

    Returns parsed dict or None if parsing fails.
    """
    # Strip markdown code fences if present
    text = response_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last lines (```json and ```)
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            return None
        return data
    except json.JSONDecodeError:
        logger.warning("Failed to parse memory update response as JSON")
        return None
