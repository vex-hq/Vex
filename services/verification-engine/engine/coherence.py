"""LLM-based coherence detection check.

Evaluates whether the latest agent output contradicts statements made
in prior conversation turns.  Returns a coherence score where 1.0 means
fully consistent and 0.0 means severe contradiction.

Explicit corrections (e.g. "I was wrong earlier...") are NOT penalized.
"""

import json
import logging
from typing import Any, List, Optional

from engine.conversation_utils import format_history
from engine.llm_client import call_llm
from engine.models import CheckResult, ConversationTurn

logger = logging.getLogger("agentguard.verification-engine.coherence")

SYSTEM_PROMPT = (
    "You are a coherence evaluator.  Given a conversation history and the "
    "agent's latest output, determine whether the latest output contradicts "
    "any statements the agent made in prior turns.\n\n"
    "IMPORTANT: Do NOT penalize explicit corrections where the agent "
    "acknowledges and corrects a prior mistake (e.g. 'I was wrong earlier', "
    "'Let me correct that', 'Actually...').\n\n"
    "Respond in JSON with this schema:\n"
    '{"contradictions": [\n'
    '  {"prior_turn": 0, "prior_statement": "...", '
    '"current_statement": "...", "explanation": "..."}\n'
    '], "score": 0.8}\n\n'
    "The score should be between 0 (severe contradictions) and 1 "
    "(fully consistent).  If there are no contradictions, return score 1.0 "
    "with an empty contradictions list."
)


async def check(
    output: Any,
    conversation_history: Optional[List[ConversationTurn]] = None,
) -> CheckResult:
    """Check agent output for self-contradictions against prior turns.

    Args:
        output: The agent's latest output to check.
        conversation_history: Prior conversation turns.  If None or empty,
            the check is skipped (coherence only applies to multi-turn).

    Returns:
        CheckResult with a coherence score.
        If no history, returns a passed result with skipped=True.
        On LLM timeout, returns score=None with error details.
    """
    if not conversation_history:
        return CheckResult(
            check_type="coherence",
            score=1.0,
            passed=True,
            details={"skipped": True},
        )

    output_str = output if isinstance(output, str) else json.dumps(output)
    history_str = format_history(conversation_history)

    prompt = (
        f"Conversation history:\n{history_str}\n\n"
        f"Latest agent output:\n{output_str}\n\n"
        "Identify any contradictions between the latest output and "
        "prior agent statements.  Return JSON as specified."
    )

    result = await call_llm(prompt, system=SYSTEM_PROMPT)

    if result is None:
        return CheckResult(
            check_type="coherence",
            score=None,
            passed=True,
            details={"error": "timeout"},
        )

    score = result.get("score")
    if score is None:
        score = 1.0

    # Clamp score to [0, 1]
    score = max(0.0, min(1.0, float(score)))

    contradictions = result.get("contradictions", [])

    return CheckResult(
        check_type="coherence",
        score=score,
        passed=score >= 0.5,
        details={"contradictions": contradictions},
    )
