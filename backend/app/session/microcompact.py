"""Microcompact — lightweight zero-LLM-cost context compression.

Inspired by Claude Code's microcompact system. Runs before every LLM call
to replace old tool outputs with compact stubs, significantly reducing
context usage without any LLM invocation.

Two layers:
  1. microcompact_messages() — replace old outputs from specific tool types
  2. apply_tool_result_budget() — enforce aggregate size limit across all tool results

OpenAI message format handled:
  - Assistant: {"role": "assistant", "tool_calls": [{"id": "call_1", "function": {"name": "read", ...}}]}
  - Tool result: {"role": "tool", "tool_call_id": "call_1", "content": "..."}
  - The tool_call_id→tool_name mapping must be built from assistant messages first.
"""

from __future__ import annotations

import logging
from typing import Any

from app.utils.token import estimate_tokens

logger = logging.getLogger(__name__)

# Tools whose old outputs can be safely replaced with stubs.
# These produce large but non-critical output that can be re-fetched.
MICROCOMPACTABLE_TOOLS = frozenset({
    "read", "grep", "bash", "glob", "search", "web_fetch",
    "edit", "write",  # Claude Code also compacts these
})

# Default thresholds
DEFAULT_MAX_TOOL_OUTPUT_TOKENS = 2000
DEFAULT_SKIP_RECENT_TURNS = 2
DEFAULT_BUDGET_TOKENS = 100_000


def _build_call_id_to_tool_name(messages: list[dict[str, Any]]) -> dict[str, str]:
    """Build a mapping from tool_call_id to tool name.

    Scans assistant messages for tool_calls arrays and extracts
    the id → function.name mapping.
    """
    mapping: dict[str, str] = {}
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            continue
        for tc in tool_calls:
            call_id = tc.get("id", "")
            func = tc.get("function", {})
            name = func.get("name", "")
            if call_id and name:
                mapping[call_id] = name
    return mapping


def _count_recent_messages(messages: list[dict[str, Any]], skip_turns: int) -> int:
    """Count how many trailing messages constitute the last N assistant turns.

    A 'turn' = one assistant message + its subsequent tool results + next user message.
    We walk backwards counting assistant messages to find the cutoff index.
    """
    if skip_turns <= 0:
        return 0

    assistant_count = 0
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "assistant":
            assistant_count += 1
            if assistant_count >= skip_turns:
                return len(messages) - i
    return 0  # Not enough turns to skip


def microcompact_messages(
    messages: list[dict[str, Any]],
    *,
    skip_recent_turns: int = DEFAULT_SKIP_RECENT_TURNS,
    max_tool_output_tokens: int = DEFAULT_MAX_TOOL_OUTPUT_TOKENS,
) -> list[dict[str, Any]]:
    """Replace old tool results from specific tool types with compact stubs.

    Zero LLM cost — pure text replacement. Runs before every LLM call.

    Args:
        messages: LLM-formatted message history (OpenAI format).
        skip_recent_turns: Number of recent assistant turns to protect.
        max_tool_output_tokens: Token threshold above which old outputs are replaced.

    Returns:
        A new message list with old tool outputs replaced by stubs.
    """
    if not messages:
        return messages

    # Build tool_call_id → tool_name mapping from all assistant messages
    call_id_map = _build_call_id_to_tool_name(messages)

    # Find cutoff: protect the last N assistant turns
    protected_count = _count_recent_messages(messages, skip_recent_turns)
    cutoff = len(messages) - protected_count
    if cutoff <= 0:
        return messages

    replaced = 0
    result = []
    for i, msg in enumerate(messages):
        if i >= cutoff:
            result.append(msg)
            continue

        if msg.get("role") != "tool":
            result.append(msg)
            continue

        # This is a tool result message
        tool_call_id = msg.get("tool_call_id", "")
        tool_name = call_id_map.get(tool_call_id, "")
        content = msg.get("content", "")

        # Only compress outputs from microcompactable tools
        if (
            tool_name in MICROCOMPACTABLE_TOOLS
            and isinstance(content, str)
            and content
        ):
            tokens = estimate_tokens(content)
            if tokens > max_tool_output_tokens:
                msg = dict(msg)
                msg["content"] = (
                    f"[Previous {tool_name} output cleared — "
                    f"{tokens} tokens. Re-run tool if needed.]"
                )
                replaced += 1

        result.append(msg)

    if replaced:
        logger.info("Microcompact: replaced %d old tool outputs", replaced)

    return result


def apply_tool_result_budget(
    messages: list[dict[str, Any]],
    *,
    budget_tokens: int = DEFAULT_BUDGET_TOKENS,
    skip_recent_turns: int = DEFAULT_SKIP_RECENT_TURNS,
) -> list[dict[str, Any]]:
    """Enforce aggregate size limit across all tool results.

    When total tool result tokens exceed the budget, replace the
    oldest/largest results first until within budget.

    Args:
        messages: LLM-formatted message history.
        budget_tokens: Maximum total tokens allowed for all tool results.
        skip_recent_turns: Number of recent assistant turns to protect.

    Returns:
        A new message list with oversized tool results replaced.
    """
    if not messages:
        return messages

    call_id_map = _build_call_id_to_tool_name(messages)

    protected_count = _count_recent_messages(messages, skip_recent_turns)
    cutoff = len(messages) - protected_count
    if cutoff <= 0:
        return messages

    # First pass: collect all tool results with their sizes
    tool_entries: list[dict[str, Any]] = []
    total_tokens = 0

    for i, msg in enumerate(messages):
        if i >= cutoff:
            continue
        if msg.get("role") != "tool":
            continue

        content = msg.get("content", "")
        if isinstance(content, str) and content:
            tokens = estimate_tokens(content)
            tool_call_id = msg.get("tool_call_id", "")
            tool_entries.append({
                "msg_index": i,
                "tokens": tokens,
                "tool_call_id": tool_call_id,
            })
            total_tokens += tokens

    if total_tokens <= budget_tokens:
        return messages

    # Sort by tokens descending — replace largest first
    tool_entries.sort(key=lambda x: x["tokens"], reverse=True)

    to_replace: set[int] = set()
    excess = total_tokens - budget_tokens

    for entry in tool_entries:
        if excess <= 0:
            break
        to_replace.add(entry["msg_index"])
        excess -= entry["tokens"]

    # Second pass: replace identified messages
    result = []
    for i, msg in enumerate(messages):
        if i in to_replace:
            msg = dict(msg)
            tokens = estimate_tokens(msg.get("content", ""))
            tool_call_id = msg.get("tool_call_id", "")
            tool_name = call_id_map.get(tool_call_id, "tool")
            msg["content"] = (
                f"[{tool_name} output removed to stay within context budget — "
                f"{tokens} tokens. Re-run tool if needed.]"
            )
        result.append(msg)

    saved = total_tokens - budget_tokens
    logger.info(
        "Tool result budget: replaced %d results, saved ~%d tokens",
        len(to_replace), saved,
    )

    return result
