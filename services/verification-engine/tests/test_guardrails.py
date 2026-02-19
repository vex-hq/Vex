"""Tests for the custom guardrails check module."""

from unittest.mock import AsyncMock, patch

import pytest

from engine.guardrails import check
from engine.models import GuardrailRule


@pytest.mark.asyncio
async def test_no_rules_skips():
    """No rules configured — check skipped, returns passed."""
    result = await check(output="hello world", rules=[])
    assert result.check_type == "guardrails"
    assert result.score == 1.0
    assert result.passed is True
    assert result.details.get("skipped") is True


@pytest.mark.asyncio
async def test_all_disabled_rules_skips():
    """All rules disabled — check skipped."""
    rules = [
        GuardrailRule(name="r1", rule_type="keyword", condition={"keywords": ["bad"]}, enabled=False),
    ]
    result = await check(output="bad output", rules=rules)
    assert result.passed is True
    assert result.details.get("skipped") is True


# --- Regex rules ---


@pytest.mark.asyncio
async def test_regex_match_triggers_violation():
    rules = [
        GuardrailRule(name="no-emails", rule_type="regex", condition={"pattern": r"\b[\w.-]+@[\w.-]+\.\w+\b"}, action="flag"),
    ]
    result = await check(output="Contact us at test@example.com", rules=rules)
    assert result.passed is False
    assert len(result.details["violations"]) == 1
    assert result.details["violations"][0]["rule_name"] == "no-emails"


@pytest.mark.asyncio
async def test_regex_no_match_passes():
    rules = [
        GuardrailRule(name="no-emails", rule_type="regex", condition={"pattern": r"\b[\w.-]+@[\w.-]+\.\w+\b"}, action="flag"),
    ]
    result = await check(output="No emails here", rules=rules)
    assert result.passed is True
    assert result.score == 1.0


@pytest.mark.asyncio
async def test_regex_case_insensitive():
    rules = [
        GuardrailRule(name="no-secret", rule_type="regex", condition={"pattern": "SECRET", "ignore_case": True}, action="block"),
    ]
    result = await check(output="this is a secret value", rules=rules)
    assert result.passed is False
    assert result.score == 0.0


@pytest.mark.asyncio
async def test_regex_empty_pattern_no_violation():
    rules = [
        GuardrailRule(name="empty", rule_type="regex", condition={"pattern": ""}, action="flag"),
    ]
    result = await check(output="anything", rules=rules)
    assert result.passed is True


# --- Keyword rules ---


@pytest.mark.asyncio
async def test_keyword_match_triggers():
    rules = [
        GuardrailRule(name="competitor-block", rule_type="keyword", condition={"keywords": ["CompetitorX", "RivalY"]}, action="block"),
    ]
    result = await check(output="I recommend trying CompetitorX for better results", rules=rules)
    assert result.passed is False
    assert result.score == 0.0
    assert "CompetitorX" in result.details["violations"][0]["matched_keywords"]


@pytest.mark.asyncio
async def test_keyword_no_match_passes():
    rules = [
        GuardrailRule(name="competitor-block", rule_type="keyword", condition={"keywords": ["CompetitorX"]}, action="block"),
    ]
    result = await check(output="Our product is the best", rules=rules)
    assert result.passed is True


@pytest.mark.asyncio
async def test_keyword_case_insensitive():
    rules = [
        GuardrailRule(name="profanity", rule_type="keyword", condition={"keywords": ["badword"], "ignore_case": True}, action="flag"),
    ]
    result = await check(output="This contains BADWORD in caps", rules=rules)
    assert result.passed is False


# --- Threshold rules ---


@pytest.mark.asyncio
async def test_threshold_exceeds_triggers():
    rules = [
        GuardrailRule(name="cost-limit", rule_type="threshold", condition={"metric": "cost_estimate", "operator": ">", "limit": 0.10}, action="flag"),
    ]
    result = await check(output="result", rules=rules, metadata={"cost_estimate": 0.25})
    assert result.passed is False
    assert result.details["violations"][0]["actual"] == 0.25


@pytest.mark.asyncio
async def test_threshold_under_limit_passes():
    rules = [
        GuardrailRule(name="cost-limit", rule_type="threshold", condition={"metric": "cost_estimate", "operator": ">", "limit": 0.10}, action="flag"),
    ]
    result = await check(output="result", rules=rules, metadata={"cost_estimate": 0.05})
    assert result.passed is True


@pytest.mark.asyncio
async def test_threshold_missing_metric_passes():
    rules = [
        GuardrailRule(name="cost-limit", rule_type="threshold", condition={"metric": "cost_estimate", "operator": ">", "limit": 0.10}, action="flag"),
    ]
    result = await check(output="result", rules=rules, metadata={})
    assert result.passed is True


@pytest.mark.asyncio
async def test_threshold_less_than_operator():
    rules = [
        GuardrailRule(name="min-tokens", rule_type="threshold", condition={"metric": "token_count", "operator": "<", "limit": 10}, action="flag"),
    ]
    result = await check(output="short", rules=rules, metadata={"token_count": 5})
    assert result.passed is False


# --- LLM rules ---


@pytest.mark.asyncio
async def test_llm_rule_violation():
    llm_response = {"violated": True, "explanation": "The output recommends a competitor"}
    rules = [
        GuardrailRule(name="no-competitor-recs", rule_type="llm", condition={"description": "Block if the agent recommends a competitor"}, action="block"),
    ]
    with patch("engine.guardrails.call_llm", new_callable=AsyncMock, return_value=llm_response):
        result = await check(output="Try using RivalCo instead", rules=rules)
    assert result.passed is False
    assert result.score == 0.0


@pytest.mark.asyncio
async def test_llm_rule_no_violation():
    llm_response = {"violated": False, "explanation": "Output is fine"}
    rules = [
        GuardrailRule(name="no-competitor-recs", rule_type="llm", condition={"description": "Block if the agent recommends a competitor"}, action="block"),
    ]
    with patch("engine.guardrails.call_llm", new_callable=AsyncMock, return_value=llm_response):
        result = await check(output="Our product handles this well", rules=rules)
    assert result.passed is True
    assert result.score == 1.0


@pytest.mark.asyncio
async def test_llm_timeout_no_violation():
    """LLM timeout should not trigger a violation."""
    rules = [
        GuardrailRule(name="safety", rule_type="llm", condition={"description": "Block harmful content"}, action="block"),
    ]
    with patch("engine.guardrails.call_llm", new_callable=AsyncMock, return_value=None):
        result = await check(output="some output", rules=rules)
    assert result.passed is True


# --- Multi-rule tests ---


@pytest.mark.asyncio
async def test_block_rule_overrides_score():
    """A single block violation should set score to 0.0."""
    rules = [
        GuardrailRule(name="keyword-flag", rule_type="keyword", condition={"keywords": ["warning"]}, action="flag"),
        GuardrailRule(name="keyword-block", rule_type="keyword", condition={"keywords": ["danger"]}, action="block"),
    ]
    result = await check(output="danger zone with warning signs", rules=rules)
    assert result.score == 0.0
    assert result.passed is False
    assert len(result.details["violations"]) == 2


@pytest.mark.asyncio
async def test_flag_violations_reduce_score_proportionally():
    """Flag violations reduce score based on ratio of violated rules."""
    rules = [
        GuardrailRule(name="r1", rule_type="keyword", condition={"keywords": ["bad"]}, action="flag"),
        GuardrailRule(name="r2", rule_type="keyword", condition={"keywords": ["evil"]}, action="flag"),
        GuardrailRule(name="r3", rule_type="keyword", condition={"keywords": ["good"]}, action="flag"),
    ]
    # 1 out of 3 rules violated → score = 1.0 - 1/3 = 0.6667
    result = await check(output="this is bad but nothing else", rules=rules)
    assert result.passed is False
    assert 0.6 < result.score < 0.7


@pytest.mark.asyncio
async def test_dict_output_serialized():
    """Dict outputs should be serialized and searchable."""
    rules = [
        GuardrailRule(name="no-secrets", rule_type="keyword", condition={"keywords": ["api_key"]}, action="flag"),
    ]
    result = await check(output={"api_key": "sk-123", "data": "value"}, rules=rules)
    assert result.passed is False


@pytest.mark.asyncio
async def test_unknown_rule_type_ignored():
    rules = [
        GuardrailRule(name="unknown", rule_type="future_type", condition={}, action="flag"),
    ]
    result = await check(output="anything", rules=rules)
    assert result.passed is True
    assert result.details["rule_results"][0]["reason"] == "unknown rule_type 'future_type'"
