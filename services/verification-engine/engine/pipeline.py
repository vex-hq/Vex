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
from engine import guardrails as guardrails_checker
from engine import hallucination
from engine import schema_validator
from engine import tool_loop
from engine.models import CheckResult, ConversationTurn, VerificationConfig, VerificationResult

logger = logging.getLogger("agentguard.verification-engine.pipeline")

COHERENCE_WEIGHT = 0.20
TOOL_LOOP_WEIGHT = 0.15
GUARDRAILS_WEIGHT = 0.20


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
        return "flag"
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
    steps: Optional[list] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> VerificationResult:
    """Run the full verification pipeline on agent output.

    1. Schema validation (deterministic, sync)
    1b. Tool loop detection (deterministic, sync, when steps provided)
    2. Hallucination + drift + optionally coherence + guardrails (async in parallel)
    3. Composite confidence score
    4. Action routing based on thresholds

    Args:
        output: The agent's output to verify.
        task: Task description for drift checking.
        schema: JSON Schema for schema validation.
        ground_truth: Reference data for hallucination checking.
        conversation_history: Prior conversation turns for conversation-aware checks.
        config: Optional verification config (weights, thresholds, guardrails).
        steps: Optional list of agent steps (tool calls, LLM calls) for loop detection.
        metadata: Optional execution metadata for threshold guardrail rules.

    Returns:
        VerificationResult with confidence, action, and per-check results.
    """
    cfg = config or VerificationConfig()

    # 1. Schema validation (deterministic, sync)
    schema_result = schema_validator.validate(output, schema)

    # 1b. Tool loop detection (deterministic, sync)
    tool_loop_result = None
    if steps:
        tool_loop_result = tool_loop.check(steps=steps)

    # 2. LLM checks in parallel
    has_history = bool(conversation_history)

    has_guardrails = bool(cfg.guardrails)

    llm_tasks = [
        hallucination.check(output, ground_truth, conversation_history),
        drift.check(output, task, conversation_history),
    ]

    if has_history:
        llm_tasks.append(coherence.check(output, conversation_history))

    if has_guardrails:
        llm_tasks.append(guardrails_checker.check(output, cfg.guardrails, metadata))

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

    if tool_loop_result is not None:
        checks["tool_loop"] = tool_loop_result
        original_total = sum(weights.values())
        if original_total > 0:
            scale = (original_total - TOOL_LOOP_WEIGHT) / original_total
            weights = {k: v * scale for k, v in weights.items()}
        weights["tool_loop"] = TOOL_LOOP_WEIGHT

    if has_guardrails:
        # Guardrails result is the last in llm_results
        guardrails_idx = 2 + (1 if has_history else 0)
        guardrails_result = llm_results[guardrails_idx]
        checks["guardrails"] = guardrails_result
        original_total = sum(weights.values())
        if original_total > 0:
            scale = (original_total - GUARDRAILS_WEIGHT) / original_total
            weights = {k: v * scale for k, v in weights.items()}
        weights["guardrails"] = GUARDRAILS_WEIGHT

    confidence = confidence_scorer.compute(checks, weights)

    # 4. Route action
    action = route_action(confidence, cfg.pass_threshold, cfg.flag_threshold)

    # 4b. Guardrails override: if any guardrail rule has action="block"
    # and was violated, force the action to "block" regardless of confidence.
    if has_guardrails and "guardrails" in checks:
        gr = checks["guardrails"]
        if not gr.passed:
            violations = gr.details.get("violations", [])
            has_block_violation = any(v.get("action") == "block" for v in violations)
            if has_block_violation:
                action = "block"
            elif action == "pass":
                action = "flag"

    return VerificationResult(
        confidence=confidence,
        action=action,
        checks=checks,
    )
