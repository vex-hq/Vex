"""Shared utilities for formatting conversation history in LLM prompts.

Provides a consistent format used by hallucination, drift, and coherence
checks to present multi-turn conversation context to the LLM judge.
"""

from __future__ import annotations

import json
from typing import Any, List

from engine.models import ConversationTurn


def _stringify(value: Any) -> str:
    """Convert a value to a string suitable for prompt inclusion."""
    if value is None:
        return "(none)"
    if isinstance(value, str):
        return value
    return json.dumps(value, default=str)


def format_history(history: List[ConversationTurn]) -> str:
    """Format conversation turns for inclusion in LLM prompts.

    Produces a structured representation of prior turns that LLM checks
    can use to evaluate cross-turn consistency, progressive drift, and
    hallucination of prior-turn content.

    Args:
        history: List of prior conversation turns (oldest first).

    Returns:
        Formatted string with each turn labelled by sequence number.
        Empty string if history is empty.
    """
    if not history:
        return ""

    parts: List[str] = []
    for turn in history:
        lines = [f"[Turn {turn.sequence_number}]"]
        if turn.task is not None:
            lines.append(f"Task: {turn.task}")
        lines.append(f"User: {_stringify(turn.input)}")
        lines.append(f"Agent: {_stringify(turn.output)}")
        parts.append("\n".join(lines))

    return "\n\n".join(parts)
