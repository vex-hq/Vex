"""LLM-based hallucination detection check.

Extracts factual claims from agent output and verifies them against
provided ground truth data.  Returns a score based on the proportion
of claims that are grounded in the reference data.

When conversation history is provided, also detects cross-turn
hallucinations — claims that incorrectly reference content from
prior conversation turns.
"""

import json
import logging
from typing import Any, List, Optional

from engine.conversation_utils import format_history
from engine.llm_client import call_llm
from engine.models import CheckResult, ConversationTurn

logger = logging.getLogger("agentguard.verification-engine.hallucination")

SYSTEM_PROMPT = (
    "You are a factual grounding evaluator.  Given an agent's output and "
    "ground truth reference data, extract all factual claims from the output "
    "and determine which ones are supported by the ground truth.\n\n"
    "Respond in JSON with this schema:\n"
    '{"claims": ["claim1", "claim2"], '
    '"grounded": ["claim1"], '
    '"ungrounded": ["claim2"], '
    '"score": 0.5}\n\n'
    "The score should be the fraction of claims that are grounded (0-1).  "
    "If there are no factual claims, return score 1.0."
)

CONVERSATION_SYSTEM_PROMPT = (
    "You are a factual grounding evaluator for multi-turn conversations.  "
    "Given a conversation history, the agent's latest output, and ground "
    "truth reference data, extract all factual claims from the latest output "
    "and determine which ones are supported by the ground truth.\n\n"
    "Also check for cross-turn hallucinations: claims that incorrectly "
    "reference or misquote content from prior conversation turns.\n\n"
    "Respond in JSON with this schema:\n"
    '{"claims": ["claim1", "claim2"], '
    '"grounded": ["claim1"], '
    '"ungrounded": ["claim2"], '
    '"cross_turn_issues": ["incorrectly referenced turn 0 data"], '
    '"score": 0.5}\n\n'
    "The score should be the fraction of claims that are grounded (0-1).  "
    "Cross-turn issues should reduce the score.  "
    "If there are no factual claims, return score 1.0."
)


async def check(
    output: Any,
    ground_truth: Any = None,
    conversation_history: Optional[List[ConversationTurn]] = None,
) -> CheckResult:
    """Check agent output for hallucinations against ground truth.

    Args:
        output: The agent's output to check.
        ground_truth: Reference data to verify claims against.
            If None, the check is skipped.
        conversation_history: Prior conversation turns.  When provided,
            the check also detects cross-turn hallucinations.

    Returns:
        CheckResult with a hallucination score.
        If no ground_truth is provided, returns a passed result with skipped=True.
        On LLM timeout, returns score=None with error details.
    """
    if ground_truth is None:
        return CheckResult(
            check_type="hallucination",
            score=1.0,
            passed=True,
            details={"skipped": True},
        )

    output_str = output if isinstance(output, str) else json.dumps(output)
    truth_str = ground_truth if isinstance(ground_truth, str) else json.dumps(ground_truth)

    # Choose prompt based on whether conversation history is available
    if conversation_history:
        history_str = format_history(conversation_history)
        prompt = (
            f"Conversation history:\n{history_str}\n\n"
            f"Latest agent output:\n{output_str}\n\n"
            f"Ground truth:\n{truth_str}\n\n"
            "Extract all factual claims from the latest output and check each "
            "against the ground truth.  Also check for cross-turn hallucinations "
            "where the output incorrectly references prior turn content.  "
            "Return JSON as specified."
        )
        system = CONVERSATION_SYSTEM_PROMPT
    else:
        prompt = (
            f"Agent output:\n{output_str}\n\n"
            f"Ground truth:\n{truth_str}\n\n"
            "Extract all factual claims from the output and check each against "
            "the ground truth.  Return JSON as specified."
        )
        system = SYSTEM_PROMPT

    result = await call_llm(prompt, system=system)

    if result is None:
        return CheckResult(
            check_type="hallucination",
            score=None,
            passed=True,
            details={"error": "timeout"},
        )

    score = result.get("score")
    if score is None:
        score = 1.0

    # Clamp score to [0, 1]
    score = max(0.0, min(1.0, float(score)))

    details = {
        "claims": result.get("claims", []),
        "grounded": result.get("grounded", []),
        "ungrounded": result.get("ungrounded", []),
    }

    cross_turn_issues = result.get("cross_turn_issues", [])
    if cross_turn_issues:
        details["cross_turn_issues"] = cross_turn_issues

    return CheckResult(
        check_type="hallucination",
        score=score,
        passed=score >= 0.5,
        details=details,
    )
