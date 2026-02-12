"""Tests for correction-related engine models."""

from engine.models import (
    CheckResult,
    CorrectionAttempt,
    CorrectionResult,
    VerificationResult,
)


def test_correction_attempt_creation():
    attempt = CorrectionAttempt(
        layer=1,
        layer_name="repair",
        input_action="flag",
        input_confidence=0.6,
        corrected_output="fixed output",
        verification={"confidence": 0.9, "action": "pass"},
        model_used="gpt-4o-mini",
        latency_ms=340.0,
        success=True,
    )
    assert attempt.layer == 1
    assert attempt.layer_name == "repair"
    assert attempt.success is True
    assert attempt.latency_ms == 340.0


def test_correction_result_creation():
    attempt = CorrectionAttempt(
        layer=2,
        layer_name="constrained_regen",
        input_action="block",
        input_confidence=0.3,
        corrected_output="regenerated output",
        verification=None,
        model_used="gpt-4o",
        latency_ms=1200.0,
        success=True,
    )
    result = CorrectionResult(
        corrected=True,
        final_output="regenerated output",
        attempts=[attempt],
        total_latency_ms=1200.0,
        escalation_path=[2],
    )
    assert result.corrected is True
    assert len(result.attempts) == 1
    assert result.escalation_path == [2]


def test_verification_result_with_correction():
    vr = VerificationResult(
        confidence=0.9,
        action="pass",
        checks={
            "schema": CheckResult(check_type="schema", score=1.0, passed=True),
        },
        correction=CorrectionResult(
            corrected=True,
            final_output="fixed",
            attempts=[],
            total_latency_ms=500.0,
            escalation_path=[1],
        ),
    )
    assert vr.correction is not None
    assert vr.correction.corrected is True


def test_verification_result_without_correction():
    """Backward compat -- correction defaults to None."""
    vr = VerificationResult(confidence=0.9, action="pass")
    assert vr.correction is None
