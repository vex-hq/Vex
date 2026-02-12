"""Verification pipeline — orchestrates all checks and computes final result.

Runs schema validation (deterministic), hallucination detection, drift
scoring, and optionally coherence checking (LLM-based, in parallel),
then computes a composite confidence score and routes the action based
on thresholds.

When conversation_history is provided, a coherence check is added and
weights are dynamically rebalanced to include it.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from engine import confidence as confidence_scorer
from engine import coherence
from engine import drift
from engine import hallucination
from engine import schema_validator
from engine.models import CheckResult, ConversationTurn, VerificationConfig, VerificationResult

logger = logging.getLogger("agentguard.verification-engine.pipeline")

COHERENCE_WEIGHT = 0.20


def _rebalance_weights(
    weights: Dict[str, float],
    coherence_weight: float,
) -> Dict[str, float]:
    """Add coherence weight and proportionally reduce existing weights.

    The original weights are scaled down so their relative proportions
    are preserved, and the new total (including coherence) sums to the
    same as the original total.

    Args:
        weights: Original check weights (e.g. schema=0.3, hallucination=0.4, drift=0.3).
        coherence_weight: Weight to assign to the coherence check.

    Returns:
        New weights dict including the coherence entry.
    """
    original_total = sum(weights.values())
    if original_total == 0:
        return {**weights, "coherence": coherence_weight}

    scale = (original_total - coherence_weight) / original_total
    rebalanced = {k: v * scale for k, v in weights.items()}
    rebalanced["coherence"] = coherence_weight
    return rebalanced


def route_action(
    confidence: Optional[float],
    pass_threshold: float,
    flag_threshold: float,
) -> str:
    """Determine the action based on confidence score and thresholds.

    Args:
        confidence: Composite confidence score, or None.
        pass_threshold: Minimum confidence for a "pass" action.
        flag_threshold: Minimum confidence for a "flag" action.

    Returns:
        "pass", "flag", or "block".
    """
    if confidence is None:
        return "pass"
    if confidence >= pass_threshold:
        return "pass"
    if confidence >= flag_threshold:
        return "flag"
    return "block"


async def verify(
    output: Any,
    task: Optional[str] = None,
    schema: Optional[Dict[str, Any]] = None,
    ground_truth: Any = None,
    conversation_history: Optional[List[ConversationTurn]] = None,
    config: Optional[VerificationConfig] = None,
) -> VerificationResult:
    """Run the full verification pipeline on agent output.

    1. Schema validation (deterministic, sync)
    2. Hallucination + drift + optionally coherence (LLM-based, async in parallel)
    3. Composite confidence score
    4. Action routing based on thresholds

    Args:
        output: The agent's output to verify.
        task: Task description for drift checking.
        schema: JSON Schema for schema validation.
        ground_truth: Reference data for hallucination checking.
        conversation_history: Prior conversation turns for conversation-aware checks.
        config: Optional verification config (weights, thresholds).

    Returns:
        VerificationResult with confidence, action, and per-check results.
    """
    cfg = config or VerificationConfig()

    # 1. Schema validation (deterministic, sync)
    schema_result = schema_validator.validate(output, schema)

    # 2. LLM checks in parallel
    has_history = bool(conversation_history)

    llm_tasks = [
        hallucination.check(output, ground_truth, conversation_history),
        drift.check(output, task, conversation_history),
    ]

    if has_history:
        llm_tasks.append(coherence.check(output, conversation_history))

    llm_results = await asyncio.gather(*llm_tasks)

    hallucination_result = llm_results[0]
    drift_result = llm_results[1]

    # 3. Compute composite confidence
    checks: Dict[str, CheckResult] = {
        "schema": schema_result,
        "hallucination": hallucination_result,
        "drift": drift_result,
    }

    if has_history:
        coherence_result = llm_results[2]
        checks["coherence"] = coherence_result
        weights = _rebalance_weights(cfg.weights, COHERENCE_WEIGHT)
    else:
        weights = cfg.weights

    confidence = confidence_scorer.compute(checks, weights)

    # 4. Route action
    action = route_action(confidence, cfg.pass_threshold, cfg.flag_threshold)

    return VerificationResult(
        confidence=confidence,
        action=action,
        checks=checks,
    )
