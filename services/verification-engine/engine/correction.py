"""Correction cascade -- graduated self-correction of failed agent outputs.

Provides three correction layers of increasing power:

1. **Repair** (small model) -- surgical fix of specific errors (schema, format).
2. **Constrained Regeneration** (strong model) -- generates fresh output with
   constraints derived from task, schema, ground truth, and conversation history.
   Does NOT see the failed output to avoid anchoring.
3. **Full Re-prompt** (strong model) -- regenerates with explicit failure
   feedback.  Last resort before blocking.

Each layer is stateless.  The sync gateway orchestrates the cascade loop,
calling ``correct()`` then re-running ``verify()`` for each attempt.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from engine.conversation_utils import format_history
from engine.llm_client import call_llm
from engine.models import (
    CheckResult,
    ConversationTurn,
    CorrectionAttempt,
    VerificationResult,
)

logger = logging.getLogger("agentguard.verification-engine.correction")

LAYER_NAMES: Dict[int, str] = {1: "repair", 2: "constrained_regen", 3: "full_reprompt"}

# Model selection: Layer 1 uses fast/cheap model, Layers 2-3 use strong model
DEFAULT_REPAIR_MODEL = "gpt-4o-mini"
DEFAULT_STRONG_MODEL = "gpt-4o"


def _get_repair_model() -> str:
    return os.environ.get("CORRECTION_REPAIR_MODEL", DEFAULT_REPAIR_MODEL)


def _get_strong_model() -> str:
    return os.environ.get("CORRECTION_STRONG_MODEL", DEFAULT_STRONG_MODEL)


def select_layer(result: VerificationResult) -> int:
    """Select the starting correction layer based on failure severity.

    Rules (evaluated in order):
    - Schema-only failure (schema failed, all others passed) -> Layer 1 (Repair)
    - Mild failure (confidence > 0.5)  -> Layer 1 (Repair)
    - Moderate failure (confidence > 0.3)  -> Layer 2 (Constrained Regen)
    - Severe failure (confidence <= 0.3 or None) -> Layer 3 (Full Re-prompt)

    Args:
        result: The failed verification result.

    Returns:
        Layer number: 1 (repair), 2 (constrained regen), or 3 (full re-prompt).
    """
    checks = result.checks

    # Schema-only failure -> Layer 1 (Repair)
    schema = checks.get("schema")
    non_schema_failed = any(
        not c.passed for name, c in checks.items() if name != "schema"
    )
    if schema and not schema.passed and not non_schema_failed:
        return 1

    # Mild failure (confidence > 0.5) -> Layer 1
    if result.confidence is not None and result.confidence > 0.5:
        return 1

    # Moderate failure (confidence > 0.3) -> Layer 2
    if result.confidence is not None and result.confidence > 0.3:
        return 2

    # Severe failure -> Layer 3
    return 3


def format_check_failures(checks: Dict[str, CheckResult]) -> str:
    """Format failed checks into a human-readable error description.

    Only includes checks that failed (passed=False).

    Args:
        checks: Dictionary of check name to CheckResult.

    Returns:
        Formatted string listing each failed check with its score and details.
    """
    parts: List[str] = []
    for name, check in checks.items():
        if not check.passed:
            details_str = json.dumps(check.details, default=str) if check.details else ""
            parts.append(
                f"- {name} (score={check.score}): {details_str}"
            )
    return "\n".join(parts) if parts else "No specific errors identified."


async def correct(
    layer: int,
    output: Any,
    task: Optional[str] = None,
    checks: Optional[Dict[str, CheckResult]] = None,
    schema: Optional[Dict[str, Any]] = None,
    ground_truth: Any = None,
    conversation_history: Optional[List[ConversationTurn]] = None,
    input_data: Any = None,
) -> CorrectionAttempt:
    """Execute a single correction attempt at the given layer.

    Args:
        layer: Which correction layer to use (1, 2, or 3).
        output: The original failed output (used by L1 and L3, NOT L2).
        task: Task description for context.
        checks: Failed check results for error details.
        schema: JSON Schema definition for structure constraints.
        ground_truth: Reference data for factual constraints.
        conversation_history: Prior turns for conversation context.
        input_data: Original input that produced the output.

    Returns:
        CorrectionAttempt with the corrected output (or None on failure).
    """
    checks = checks or {}
    layer_name = LAYER_NAMES.get(layer, "unknown")
    start = time.monotonic()

    if layer == 1:
        corrected_output, model = await _layer1_repair(output, checks)
    elif layer == 2:
        corrected_output, model = await _layer2_constrained_regen(
            task, checks, schema, ground_truth, conversation_history, input_data,
        )
    else:
        corrected_output, model = await _layer3_full_reprompt(
            output, task, checks, schema, ground_truth, conversation_history, input_data,
        )

    elapsed_ms = (time.monotonic() - start) * 1000.0

    return CorrectionAttempt(
        layer=layer,
        layer_name=layer_name,
        input_action="",  # filled by gateway
        input_confidence=None,  # filled by gateway
        corrected_output=corrected_output,
        verification=None,  # filled after re-verify
        model_used=model,
        latency_ms=elapsed_ms,
        success=corrected_output is not None,
    )


async def _layer1_repair(
    output: Any,
    checks: Dict[str, CheckResult],
) -> Tuple[Any, str]:
    """Layer 1: Surgical repair of specific errors.

    Uses a small/fast model to make targeted fixes. The failed output is
    shown to the model so it can apply minimal edits.
    """
    model = _get_repair_model()
    output_str = output if isinstance(output, str) else json.dumps(output, default=str)
    failures = format_check_failures(checks)

    prompt = (
        "You are a data repair tool. Fix ONLY the specific errors listed below.\n"
        "Do NOT change content, meaning, or add information. Make the minimum "
        "edit needed to fix each error.\n\n"
        f"ORIGINAL OUTPUT:\n{output_str}\n\n"
        f"ERRORS TO FIX:\n{failures}\n\n"
        "Return JSON with this schema:\n"
        '{"corrected_output": "<the fixed output>"}\n\n'
        "If the original output is JSON, the corrected_output should also be valid JSON. "
        "Return ONLY the JSON response."
    )

    system = (
        "You are a precise data repair tool. You fix exactly the errors specified "
        "and make no other changes. Respond only in valid JSON."
    )

    result = await call_llm(prompt, system=system)
    if result is None:
        return None, model

    corrected = result.get("corrected_output")
    if corrected is None:
        corrected = result.get("output")

    # Try to parse if it looks like JSON
    if isinstance(corrected, str):
        try:
            corrected = json.loads(corrected)
        except (json.JSONDecodeError, TypeError):
            pass  # keep as string

    return corrected, model


async def _layer2_constrained_regen(
    task: Optional[str],
    checks: Dict[str, CheckResult],
    schema: Optional[Dict[str, Any]],
    ground_truth: Any,
    conversation_history: Optional[List[ConversationTurn]],
    input_data: Any,
) -> Tuple[Any, str]:
    """Layer 2: Constrained regeneration -- fresh output WITHOUT the failed output.

    This is the key differentiator: by not showing the failed output, the model
    avoids anchoring on incorrect content.  Constraints from schema, ground truth,
    and conversation history guide the regeneration.
    """
    model = _get_strong_model()

    constraints: List[str] = []
    if schema:
        constraints.append(f"You MUST follow this schema: {json.dumps(schema)}")
    if ground_truth:
        truth_str = ground_truth if isinstance(ground_truth, str) else json.dumps(ground_truth, default=str)
        constraints.append(f"Ground truth facts (do NOT contradict): {truth_str}")

    constraints_str = "\n".join(f"- {c}" for c in constraints) if constraints else "None specified."

    history_section = ""
    if conversation_history:
        history_str = format_history(conversation_history)
        history_section = f"\nCONVERSATION HISTORY:\n{history_str}\n"

    input_section = ""
    if input_data is not None:
        input_str = input_data if isinstance(input_data, str) else json.dumps(input_data, default=str)
        input_section = f"\nINPUT CONTEXT:\n{input_str}\n"

    prompt = (
        "You are a reliable AI assistant. Generate a response for the following task.\n\n"
        f"TASK: {task or 'Not specified'}\n"
        f"{input_section}"
        f"\nCONSTRAINTS:\n{constraints_str}\n"
        f"{history_section}"
        "\nRequirements:\n"
        "1. Be factually accurate and consistent with ground truth\n"
        "2. Stay focused on the task\n"
        "3. Be consistent with prior conversation turns\n"
        "4. Follow the schema exactly if one is provided\n\n"
        "Return JSON with this schema:\n"
        '{"output": "<your generated response>"}\n\n'
        "Return ONLY the JSON response."
    )

    system = (
        "You are a reliable AI assistant that generates accurate, on-task responses. "
        "You must follow all provided constraints exactly. Respond only in valid JSON."
    )

    result = await call_llm(prompt, system=system)
    if result is None:
        return None, model

    corrected = result.get("output")
    if corrected is None:
        corrected = result.get("corrected_output")
    if corrected is None:
        corrected = result.get("response")

    if isinstance(corrected, str):
        try:
            corrected = json.loads(corrected)
        except (json.JSONDecodeError, TypeError):
            pass

    return corrected, model


async def _layer3_full_reprompt(
    output: Any,
    task: Optional[str],
    checks: Dict[str, CheckResult],
    schema: Optional[Dict[str, Any]],
    ground_truth: Any,
    conversation_history: Optional[List[ConversationTurn]],
    input_data: Any,
) -> Tuple[Any, str]:
    """Layer 3: Full re-prompt with explicit failure feedback.

    Last resort -- the model sees what went wrong and is instructed to avoid
    those specific problems.  Uses the strong model for maximum capability.
    """
    model = _get_strong_model()

    output_str = output if isinstance(output, str) else json.dumps(output, default=str)
    failures = format_check_failures(checks)

    constraints: List[str] = []
    if schema:
        constraints.append(f"Schema: {json.dumps(schema)}")
    if ground_truth:
        truth_str = ground_truth if isinstance(ground_truth, str) else json.dumps(ground_truth, default=str)
        constraints.append(f"Ground truth: {truth_str}")

    constraints_str = "\n".join(f"- {c}" for c in constraints) if constraints else "None specified."

    history_section = ""
    if conversation_history:
        history_str = format_history(conversation_history)
        history_section = f"\nConversation history:\n{history_str}\n"

    input_section = ""
    if input_data is not None:
        input_str = input_data if isinstance(input_data, str) else json.dumps(input_data, default=str)
        input_section = f"\nINPUT CONTEXT:\n{input_str}\n"

    prompt = (
        "You are a reliable AI assistant. A previous response to this task "
        "FAILED verification. Generate a corrected response.\n\n"
        f"TASK: {task or 'Not specified'}\n"
        f"{input_section}"
        f"\nWHAT WENT WRONG:\n{failures}\n"
        f"\nCONSTRAINTS:\n{constraints_str}\n"
        f"{history_section}"
        "\nCRITICAL: The previous response failed because of the issues above. "
        "Your response MUST avoid these specific problems. Be conservative "
        "and precise. When uncertain, acknowledge uncertainty rather than "
        "fabricate.\n\n"
        "Return JSON with this schema:\n"
        '{"output": "<your corrected response>"}\n\n'
        "Return ONLY the JSON response."
    )

    system = (
        "You are a reliable AI assistant that must avoid the specific failures "
        "described. Be conservative and precise. Respond only in valid JSON."
    )

    result = await call_llm(prompt, system=system)
    if result is None:
        return None, model

    corrected = result.get("output")
    if corrected is None:
        corrected = result.get("corrected_output")
    if corrected is None:
        corrected = result.get("response")

    if isinstance(corrected, str):
        try:
            corrected = json.loads(corrected)
        except (json.JSONDecodeError, TypeError):
            pass

    return corrected, model
