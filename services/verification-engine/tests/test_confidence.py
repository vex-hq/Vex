"""Tests for the composite confidence score computation."""

from engine.confidence import compute
from engine.models import CheckResult


def test_weighted_composite():
    checks = {
        "schema": CheckResult(check_type="schema", score=1.0, passed=True),
        "hallucination": CheckResult(check_type="hallucination", score=0.8, passed=True),
        "drift": CheckResult(check_type="drift", score=0.6, passed=True),
    }
    weights = {"schema": 0.3, "hallucination": 0.4, "drift": 0.3}
    result = compute(checks, weights)
    # (0.3*1.0 + 0.4*0.8 + 0.3*0.6) / (0.3+0.4+0.3) = (0.3+0.32+0.18)/1.0 = 0.8
    assert result is not None
    assert abs(result - 0.8) < 1e-6


def test_skip_none_scores():
    checks = {
        "schema": CheckResult(check_type="schema", score=1.0, passed=True),
        "hallucination": CheckResult(check_type="hallucination", score=None, passed=True),
        "drift": CheckResult(check_type="drift", score=0.6, passed=True),
    }
    weights = {"schema": 0.3, "hallucination": 0.4, "drift": 0.3}
    result = compute(checks, weights)
    # hallucination skipped: (0.3*1.0 + 0.3*0.6) / (0.3+0.3) = 0.48/0.6 = 0.8
    assert result is not None
    assert abs(result - 0.8) < 1e-6


def test_all_none_returns_none():
    checks = {
        "schema": CheckResult(check_type="schema", score=None, passed=True),
        "hallucination": CheckResult(check_type="hallucination", score=None, passed=True),
        "drift": CheckResult(check_type="drift", score=None, passed=True),
    }
    weights = {"schema": 0.3, "hallucination": 0.4, "drift": 0.3}
    result = compute(checks, weights)
    assert result is None


def test_single_check_with_score():
    checks = {
        "schema": CheckResult(check_type="schema", score=0.5, passed=False),
        "hallucination": CheckResult(check_type="hallucination", score=None, passed=True),
        "drift": CheckResult(check_type="drift", score=None, passed=True),
    }
    weights = {"schema": 0.3, "hallucination": 0.4, "drift": 0.3}
    result = compute(checks, weights)
    # Only schema has a score: 0.3*0.5 / 0.3 = 0.5
    assert result is not None
    assert abs(result - 0.5) < 1e-6


def test_zero_weight_check_ignored():
    checks = {
        "schema": CheckResult(check_type="schema", score=1.0, passed=True),
        "hallucination": CheckResult(check_type="hallucination", score=0.0, passed=False),
    }
    weights = {"schema": 1.0, "hallucination": 0.0}
    result = compute(checks, weights)
    assert result is not None
    assert abs(result - 1.0) < 1e-6
