"""Memory tool — list, save, update, or forget long-term memory facts and context.

Gives the AI agent explicit control over the memory system, complementing
the passive post-conversation extraction in app/memory/queue.py.
"""

from __future__ import annotations

import logging
from typing import Any

from app.tool.base import ToolDefinition, ToolResult
from app.tool.context import ToolContext

logger = logging.getLogger(__name__)

VALID_CATEGORIES = {"preference", "knowledge", "context", "behavior", "goal"}
VALID_SECTIONS = {"work_context", "personal_context", "top_of_mind"}


class MemoryTool(ToolDefinition):

    @property
    def id(self) -> str:
        return "memory"

    @property
    def description(self) -> str:
        return (
            "Manage long-term memory that persists across conversations.\n\n"
            "IMPORTANT: Before saving a new fact, use 'search' to check if a similar fact "
            "already exists. If it does, use 'update' instead of 'save' to avoid duplicates.\n\n"
            "Commands:\n"
            "- search: Search stored facts by keywords (or omit query to list all)\n"
            "- save: Save a new fact to memory\n"
            "- update: Update an existing fact by ID (use after search)\n"
            "- update_context: Update a context summary (work_context, personal_context, or top_of_mind)\n"
            "- forget: Remove facts matching the given description"
        )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "enum": ["search", "save", "update", "update_context", "forget"],
                    "description": "The memory operation to perform",
                },
                "id": {
                    "type": "string",
                    "description": "Fact ID to update (update command only). Get IDs from the search command.",
                },
                "content": {
                    "type": "string",
                    "description": (
                        "For 'search': keywords to filter facts (omit to list all). "
                        "For 'save': the fact to remember. "
                        "For 'update': the new content for the fact. "
                        "For 'forget': keywords to match against existing facts."
                    ),
                },
                "category": {
                    "type": "string",
                    "enum": ["preference", "knowledge", "context", "behavior", "goal"],
                    "description": "Category for the fact (save/update only). Defaults to 'context'.",
                },
                "section": {
                    "type": "string",
                    "enum": ["work_context", "personal_context", "top_of_mind"],
                    "description": "Which context section to update (update_context command only).",
                },
                "summary": {
                    "type": "string",
                    "description": "The new summary text for the context section (update_context command only).",
                },
            },
            "required": ["command"],
        }

    async def execute(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        command = args.get("command", "")

        app_state = getattr(ctx, "_app_state", None)
        if not app_state or "session_factory" not in app_state:
            return ToolResult(
                error="Memory system unavailable (no database connection).",
            )

        session_factory = app_state["session_factory"]

        if command == "search":
            return await self._search(args, session_factory)
        elif command == "save":
            return await self._save(args, ctx, session_factory)
        elif command == "update":
            return await self._update(args, session_factory)
        elif command == "update_context":
            return await self._update_context(args, session_factory)
        elif command == "forget":
            return await self._forget(args, session_factory)
        else:
            return ToolResult(
                error=f"Unknown command: {command}. Use 'search', 'save', 'update', 'update_context', or 'forget'.",
            )

    async def _search(self, args: dict[str, Any], session_factory: Any) -> ToolResult:
        from app.memory.storage import get_all_facts, get_all_contexts

        query = (args.get("content") or "").strip().lower()
        facts = await get_all_facts(session_factory)

        # Filter by keywords if query provided
        if query:
            keywords = query.split()
            facts = [
                f for f in facts
                if any(kw in f["content"].lower() for kw in keywords)
                or any(kw in f["category"].lower() for kw in keywords)
            ]

        lines = []

        # Only show contexts when no search query (full listing)
        if not query:
            contexts = await get_all_contexts(session_factory)
            if any(contexts.values()):
                lines.append("## Contexts")
                labels = {"work_context": "Work", "personal_context": "Personal", "top_of_mind": "Current Focus"}
                for section, label in labels.items():
                    summary = contexts.get(section, "")
                    if summary:
                        lines.append(f"- **{label}**: {summary}")
                lines.append("")

        # Facts
        if facts:
            header = f"## Facts matching '{query}' ({len(facts)})" if query else f"## All Facts ({len(facts)})"
            lines.append(header)
            for f in facts:
                lines.append(f"- [{f['id']}] [{f['category']}] {f['content']}")
        else:
            if query:
                lines.append(f"No facts matching '{query}'.")
            else:
                lines.append("No facts stored yet.")

        return ToolResult(
            output="\n".join(lines),
            title=f"Memory: {len(facts)} fact(s)" + (f" matching '{query}'" if query else ""),
        )

    async def _save(self, args: dict[str, Any], ctx: ToolContext, session_factory: Any) -> ToolResult:
        from app.memory.storage import add_facts

        content = (args.get("content") or "").strip()
        if not content:
            return ToolResult(error="Content is required for the 'save' command.")

        category = args.get("category", "context")
        if category not in VALID_CATEGORIES:
            category = "context"

        added = await add_facts(
            session_factory,
            [{"content": content, "category": category, "confidence": 0.95}],
            source_session_id=ctx.session_id,
        )

        if added > 0:
            logger.info("MemoryTool: saved fact [%s] %s", category, content[:80])
            return ToolResult(
                output=f"Saved to memory: [{category}] {content}",
                title="Memory saved",
            )
        else:
            return ToolResult(
                output="This fact already exists in memory (duplicate).",
                title="Memory (duplicate)",
            )

    async def _update(self, args: dict[str, Any], session_factory: Any) -> ToolResult:
        from app.memory.storage import update_fact

        fact_id = (args.get("id") or "").strip()
        if not fact_id:
            return ToolResult(error="'id' is required for the 'update' command. Use 'search' first to get fact IDs.")

        content = (args.get("content") or "").strip() or None
        category = args.get("category")
        if category and category not in VALID_CATEGORIES:
            category = None

        if not content and not category:
            return ToolResult(error="Provide 'content' and/or 'category' to update.")

        found = await update_fact(
            session_factory,
            fact_id,
            content=content,
            category=category,
        )

        if found:
            logger.info("MemoryTool: updated fact %s", fact_id)
            parts = []
            if content:
                parts.append(f"content → {content}")
            if category:
                parts.append(f"category → {category}")
            return ToolResult(
                output=f"Updated fact {fact_id}: {', '.join(parts)}",
                title="Memory updated",
            )
        else:
            return ToolResult(
                error=f"Fact {fact_id} not found. Use 'search' to find facts.",
            )

    async def _update_context(self, args: dict[str, Any], session_factory: Any) -> ToolResult:
        from app.memory.storage import upsert_context

        section = args.get("section", "")
        summary = (args.get("summary") or "").strip()

        if section not in VALID_SECTIONS:
            return ToolResult(
                error=f"Invalid section: {section}. Use one of: {', '.join(VALID_SECTIONS)}",
            )
        if not summary:
            return ToolResult(error="Summary is required for the 'update_context' command.")

        await upsert_context(session_factory, section, summary)

        label = {"work_context": "Work", "personal_context": "Personal", "top_of_mind": "Current Focus"}
        logger.info("MemoryTool: updated context [%s]", section)
        return ToolResult(
            output=f"Updated {label.get(section, section)} context: {summary}",
            title=f"Context updated ({label.get(section, section)})",
        )

    async def _forget(self, args: dict[str, Any], session_factory: Any) -> ToolResult:
        from app.memory.storage import get_all_facts, remove_facts

        query = (args.get("content") or "").strip().lower()
        if not query:
            return ToolResult(error="Content is required for the 'forget' command (keywords to match).")

        all_facts = await get_all_facts(session_factory)

        # Find facts whose content contains the query keywords
        keywords = query.split()
        matching_ids = []
        matching_contents = []
        for fact in all_facts:
            fact_lower = fact["content"].lower()
            if all(kw in fact_lower for kw in keywords):
                matching_ids.append(fact["id"])
                matching_contents.append(fact["content"])

        if not matching_ids:
            return ToolResult(
                output=f"No facts found matching '{query}'.",
                title="Memory (nothing to forget)",
            )

        removed = await remove_facts(session_factory, matching_ids)
        logger.info("MemoryTool: forgot %d fact(s) matching '%s'", removed, query[:50])

        lines = [f"Removed {removed} fact(s):"]
        for c in matching_contents[:5]:
            lines.append(f"  - {c}")
        if len(matching_contents) > 5:
            lines.append(f"  ... and {len(matching_contents) - 5} more")

        return ToolResult(
            output="\n".join(lines),
            title=f"Forgot {removed} fact(s)",
        )
