"""API routes for the Sync Verification Gateway.

Provides:
- ``GET /health`` -- service health check.
- ``POST /v1/verify`` -- synchronous verification of agent output,
  with optional correction cascade (up to 2 attempts, 10 s budget).
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, Request

from shared.models import (
    CheckResult as SharedCheckResult,
    CorrectionAttemptResponse,
    VerifyRequest,
    VerifyResponse,
)

from engine.correction import correct as run_correction, select_layer
from engine.models import CorrectionAttempt, VerificationConfig, VerificationResult
from engine.pipeline import verify as run_verification

from app.auth import verify_api_key

logger = logging.getLogger("agentguard.sync-gateway")

VERIFIED_STREAM_KEY = "executions.verified"
RAW_STREAM_KEY = "executions.raw"
GATEWAY_TIMEOUT_S = 2.0
CORRECTION_TIMEOUT_S = 10.0
MAX_CORRECTION_ATTEMPTS = 2

router = APIRouter()


def _engine_checks_to_shared(
    checks: Dict[str, Any],
) -> Dict[str, SharedCheckResult]:
    """Convert engine CheckResult dicts to shared CheckResult models."""
    shared: Dict[str, SharedCheckResult] = {}
    for name, check in checks.items():
        shared[name] = SharedCheckResult(
            check_type=check.check_type,
            score=check.score if check.score is not None else 0.0,
            passed=check.passed,
            details=check.details,
        )
    return shared


async def _verify_and_correct(
    event: VerifyRequest,
    config: VerificationConfig,
    correction_mode: str,
) -> Tuple[VerificationResult, Any, bool, Optional[List[CorrectionAttempt]]]:
    """Run initial verification and optional correction cascade.

    This entire coroutine runs under a single ``asyncio.wait_for`` so the
    total wall-clock time (verify + correct + re-verify) is bounded.

    Returns:
        (result, final_output, corrected, correction_attempts)
    """
    # --- Initial verification ---
    result = await run_verification(
        output=event.output,
        task=event.task,
        schema=event.schema_definition,
        ground_truth=event.ground_truth,
        conversation_history=event.conversation_history,
        config=config,
    )

    final_output = event.output
    corrected = False
    correction_attempts: Optional[List[CorrectionAttempt]] = None

    # --- Correction cascade (only when enabled AND initial check failed) ---
    if correction_mode == "cascade" and result.action != "pass":
        original_output = event.output
        correction_attempts = []
        current_layer = select_layer(result)

        for _attempt_idx in range(MAX_CORRECTION_ATTEMPTS):
            # Always correct from the original output (never from a prior fix)
            attempt = await run_correction(
                layer=current_layer,
                output=original_output,
                task=event.task,
                checks=result.checks,
                schema=event.schema_definition,
                ground_truth=event.ground_truth,
                conversation_history=event.conversation_history,
                input_data=event.input,
            )

            # Fill in context from the current verification result
            attempt.input_action = result.action
            attempt.input_confidence = result.confidence
            correction_attempts.append(attempt)

            # If correction produced no output (LLM timeout), escalate
            if attempt.corrected_output is None:
                current_layer = min(current_layer + 1, 3)
                continue

            # Re-verify the corrected output
            result = await run_verification(
                output=attempt.corrected_output,
                task=event.task,
                schema=event.schema_definition,
                ground_truth=event.ground_truth,
                conversation_history=event.conversation_history,
                config=config,
            )

            if result.action == "pass":
                corrected = True
                final_output = attempt.corrected_output
                break

            # Re-verification failed -- escalate to next layer
            current_layer = min(current_layer + 1, 3)

    return result, final_output, corrected, correction_attempts


@router.get("/health")
async def health_check():
    """Return service health status."""
    return {"status": "healthy"}


@router.post("/v1/verify", response_model=VerifyResponse)
async def verify_endpoint(
    event: VerifyRequest,
    request: Request,
    _api_key: str = Depends(verify_api_key),
):
    """Verify an agent's output synchronously.

    Behaviour depends on the ``correction`` metadata flag:

    * ``correction=none`` (default) -- 2 s timeout, verify only.
    * ``correction=cascade`` -- 10 s timeout, verify then auto-correct
      with up to 2 graduated correction attempts if the output fails.

    Always emits to Redis streams for async storage and alerting.
    """
    redis = request.app.state.redis

    # Extract config from request metadata
    thresholds: Dict[str, Any] = {}
    correction_mode = "none"
    transparency = "opaque"

    if hasattr(event, "metadata") and event.metadata:
        thresholds = event.metadata.get("thresholds", {})
        correction_mode = event.metadata.get("correction", "none")
        transparency = event.metadata.get("transparency", "opaque")

    config = VerificationConfig(
        pass_threshold=thresholds.get("pass_threshold", 0.8),
        flag_threshold=thresholds.get("flag_threshold", 0.5),
    )

    # Dynamic timeout: 10 s for correction cascade, 2 s for verify-only
    timeout = CORRECTION_TIMEOUT_S if correction_mode == "cascade" else GATEWAY_TIMEOUT_S

    try:
        result, final_output, corrected, correction_attempts = await asyncio.wait_for(
            _verify_and_correct(event, config, correction_mode),
            timeout=timeout,
        )

        # Build shared check results
        checks = _engine_checks_to_shared(result.checks)

        # Build correction attempt responses for the wire format
        attempt_responses: Optional[List[CorrectionAttemptResponse]] = None
        if transparency == "transparent" and corrected and correction_attempts:
            attempt_responses = [
                CorrectionAttemptResponse(
                    layer=a.layer,
                    layer_name=a.layer_name,
                    corrected_output=a.corrected_output,
                    confidence=result.confidence if a == correction_attempts[-1] else None,
                    action=result.action if a == correction_attempts[-1] else "",
                    success=a.success,
                    latency_ms=a.latency_ms,
                )
                for a in correction_attempts
            ]

        response = VerifyResponse(
            execution_id=event.execution_id,
            confidence=result.confidence,
            action=result.action,
            output=final_output,
            checks=checks,
            corrected=corrected,
            original_output=event.output if corrected and transparency == "transparent" else None,
            correction_attempts=attempt_responses,
        )

    except asyncio.TimeoutError:
        logger.warning(
            "Verification timed out for event %s; returning pass-through",
            event.execution_id,
        )
        response = VerifyResponse(
            execution_id=event.execution_id,
            confidence=None,
            action="pass",
            output=event.output,
            corrected=False,
        )

    # Emit to Redis streams for async processing
    try:
        verified_data = {
            "execution_id": event.execution_id,
            "agent_id": event.agent_id,
            "confidence": str(response.confidence) if response.confidence is not None else "",
            "action": response.action,
            "checks": json.dumps(
                {k: v.model_dump(mode="json") for k, v in response.checks.items()}
            ) if response.checks else "{}",
            "corrected": str(response.corrected),
        }

        if response.corrected and response.original_output is not None:
            verified_data["original_output"] = (
                response.original_output
                if isinstance(response.original_output, str)
                else json.dumps(response.original_output, default=str)
            )

        if response.correction_attempts:
            verified_data["correction_attempts"] = json.dumps(
                [a.model_dump(mode="json") for a in response.correction_attempts]
            )

        await redis.xadd(VERIFIED_STREAM_KEY, {"data": json.dumps(verified_data)})

        # Also emit raw event for storage worker to persist the execution
        await redis.xadd(RAW_STREAM_KEY, {"data": event.model_dump_json()})
    except Exception:
        logger.warning(
            "Failed to emit Redis events for %s", event.execution_id, exc_info=True,
        )

    return response
