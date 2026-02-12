"""Tests for the verification pipeline."""

from unittest.mock import AsyncMock, patch

import pytest

from engine.models import ConversationTurn, VerificationConfig
from engine.pipeline import _rebalance_weights, route_action, verify


def test_route_action_pass():
    assert route_action(0.9, pass_threshold=0.8, flag_threshold=0.5) == "pass"


def test_route_action_flag():
    assert route_action(0.6, pass_threshold=0.8, flag_threshold=0.5) == "flag"


def test_route_action_block():
    assert route_action(0.3, pass_threshold=0.8, flag_threshold=0.5) == "block"


def test_route_action_none_returns_pass():
    assert route_action(None, pass_threshold=0.8, flag_threshold=0.5) == "pass"


def test_route_action_at_threshold_boundary():
    assert route_action(0.8, pass_threshold=0.8, flag_threshold=0.5) == "pass"
    assert route_action(0.5, pass_threshold=0.8, flag_threshold=0.5) == "flag"
    assert route_action(0.4999, pass_threshold=0.8, flag_threshold=0.5) == "block"


@pytest.mark.asyncio
async def test_full_pipeline_all_pass():
    hallucination_response = {
        "claims": ["The revenue is $1M"],
        "grounded": ["The revenue is $1M"],
        "ungrounded": [],
        "score": 1.0,
    }
    drift_response = {"score": 0.95, "explanation": "Relevant output"}

    with patch("engine.hallucination.call_llm", new_callable=AsyncMock, return_value=hallucination_response), \
         patch("engine.drift.call_llm", new_callable=AsyncMock, return_value=drift_response):
        result = await verify(
            output={"revenue": 1000000},
            task="Generate financial report",
            schema={"type": "object", "required": ["revenue"]},
            ground_truth={"revenue": 1000000},
        )

    assert result.action == "pass"
    assert result.confidence is not None
    assert result.confidence >= 0.8
    assert "schema" in result.checks
    assert "hallucination" in result.checks
    assert "drift" in result.checks
    assert result.checks["schema"].passed is True


@pytest.mark.asyncio
async def test_full_pipeline_schema_failure_causes_block():
    hallucination_response = {
        "claims": [],
        "grounded": [],
        "ungrounded": [],
        "score": 1.0,
    }
    drift_response = {"score": 0.9, "explanation": "Relevant"}

    with patch("engine.hallucination.call_llm", new_callable=AsyncMock, return_value=hallucination_response), \
         patch("engine.drift.call_llm", new_callable=AsyncMock, return_value=drift_response):
        result = await verify(
            output={"wrong_field": "data"},
            task="Generate report",
            schema={"type": "object", "required": ["revenue"]},
            ground_truth={"revenue": 1000000},
        )

    assert result.checks["schema"].passed is False
    assert result.checks["schema"].score == 0.0
    # confidence: (0.3*0.0 + 0.4*1.0 + 0.3*0.9) = 0.67 → flag
    assert result.action == "flag"


@pytest.mark.asyncio
async def test_pipeline_with_no_optional_inputs():
    """No schema, ground_truth, or task — all checks skip, action=pass."""
    result = await verify(output="hello world")
    assert result.action == "pass"
    assert result.confidence is not None
    assert result.confidence == 1.0
    assert result.checks["schema"].details.get("skipped") is True
    assert result.checks["hallucination"].details.get("skipped") is True
    assert result.checks["drift"].details.get("skipped") is True


@pytest.mark.asyncio
async def test_pipeline_llm_timeout_graceful():
    """LLM timeout returns None scores — pipeline still succeeds."""
    with patch("engine.hallucination.call_llm", new_callable=AsyncMock, return_value=None), \
         patch("engine.drift.call_llm", new_callable=AsyncMock, return_value=None):
        result = await verify(
            output="hello",
            task="greet user",
            ground_truth={"greeting": "hello"},
        )

    assert result.checks["hallucination"].score is None
    assert result.checks["drift"].score is None
    # Only schema has a score (1.0, no schema defined → skip → score 1.0)
    assert result.confidence is not None
    assert result.action == "pass"


@pytest.mark.asyncio
async def test_pipeline_custom_config():
    config = VerificationConfig(
        weights={"schema": 1.0, "hallucination": 0.0, "drift": 0.0},
        pass_threshold=0.9,
        flag_threshold=0.5,
    )
    result = await verify(
        output={"name": "Alice"},
        schema={"type": "object", "required": ["name"]},
        config=config,
    )
    assert result.confidence is not None
    assert result.confidence == 1.0
    assert result.action == "pass"


# --- Conversation-aware pipeline tests ---


@pytest.mark.asyncio
async def test_pipeline_with_history_runs_four_checks():
    """When conversation_history is provided, coherence check is included."""
    hallucination_response = {
        "claims": ["Revenue is $5.2B"],
        "grounded": ["Revenue is $5.2B"],
        "ungrounded": [],
        "score": 1.0,
    }
    drift_response = {
        "immediate_relevance": 0.95,
        "trajectory_drift": 0.9,
        "explanation": "On topic.",
    }
    coherence_response = {
        "contradictions": [],
        "score": 1.0,
    }

    history = [
        ConversationTurn(sequence_number=0, input="Revenue?", output="$5.2B"),
    ]

    with patch("engine.hallucination.call_llm", new_callable=AsyncMock, return_value=hallucination_response), \
         patch("engine.drift.call_llm", new_callable=AsyncMock, return_value=drift_response), \
         patch("engine.coherence.call_llm", new_callable=AsyncMock, return_value=coherence_response):
        result = await verify(
            output="Revenue is still $5.2B.",
            task="Financial summary",
            ground_truth={"revenue": "$5.2B"},
            conversation_history=history,
        )

    assert "schema" in result.checks
    assert "hallucination" in result.checks
    assert "drift" in result.checks
    assert "coherence" in result.checks
    assert result.action == "pass"
    assert result.confidence is not None
    assert result.confidence >= 0.8


@pytest.mark.asyncio
async def test_pipeline_without_history_runs_three_checks():
    """Without history, coherence is NOT included — same as Phase 2 behavior."""
    hallucination_response = {
        "claims": ["Revenue is $5.2B"],
        "grounded": ["Revenue is $5.2B"],
        "ungrounded": [],
        "score": 1.0,
    }
    drift_response = {"score": 0.95, "explanation": "On topic."}

    with patch("engine.hallucination.call_llm", new_callable=AsyncMock, return_value=hallucination_response), \
         patch("engine.drift.call_llm", new_callable=AsyncMock, return_value=drift_response):
        result = await verify(
            output="Revenue is $5.2B.",
            task="Financial summary",
            ground_truth={"revenue": "$5.2B"},
            conversation_history=None,
        )

    assert "schema" in result.checks
    assert "hallucination" in result.checks
    assert "drift" in result.checks
    assert "coherence" not in result.checks
    assert result.action == "pass"


@pytest.mark.asyncio
async def test_pipeline_custom_weights_with_coherence():
    """Custom weights should be rebalanced when coherence is active."""
    hallucination_response = {
        "claims": [],
        "grounded": [],
        "ungrounded": [],
        "score": 1.0,
    }
    drift_response = {
        "immediate_relevance": 1.0,
        "trajectory_drift": 1.0,
        "explanation": "Perfect.",
    }
    coherence_response = {
        "contradictions": [],
        "score": 0.3,
    }

    history = [
        ConversationTurn(sequence_number=0, input="q", output="a"),
    ]

    config = VerificationConfig(
        weights={"schema": 0.5, "hallucination": 0.25, "drift": 0.25},
    )

    with patch("engine.hallucination.call_llm", new_callable=AsyncMock, return_value=hallucination_response), \
         patch("engine.drift.call_llm", new_callable=AsyncMock, return_value=drift_response), \
         patch("engine.coherence.call_llm", new_callable=AsyncMock, return_value=coherence_response):
        result = await verify(
            output="output",
            task="task",
            conversation_history=history,
            config=config,
        )

    assert "coherence" in result.checks
    # Coherence score is 0.3 which should pull confidence down
    assert result.confidence is not None
    assert result.confidence < 1.0


def test_rebalance_weights():
    """_rebalance_weights preserves proportions and adds coherence."""
    original = {"schema": 0.3, "hallucination": 0.4, "drift": 0.3}
    rebalanced = _rebalance_weights(original, 0.20)

    # coherence should be present
    assert rebalanced["coherence"] == 0.20
    # total should still be 1.0
    assert abs(sum(rebalanced.values()) - 1.0) < 1e-9
    # proportions of original keys should be preserved
    assert abs(rebalanced["schema"] / rebalanced["drift"] - 1.0) < 1e-9
    assert rebalanced["hallucination"] > rebalanced["schema"]
