import uuid
from datetime import datetime, timezone

from vex.models import (
    ConversationTurn,
    ExecutionEvent,
    VexResult,
    StepRecord,
    ThresholdConfig,
)


def test_threshold_config_defaults():
    config = ThresholdConfig()
    assert config.pass_threshold == 0.8
    assert config.flag_threshold == 0.5
    assert config.block_threshold == 0.3


def test_threshold_config_custom():
    config = ThresholdConfig(
        pass_threshold=0.9, flag_threshold=0.6, block_threshold=0.4
    )
    assert config.pass_threshold == 0.9


def test_threshold_config_validation_rejects_invalid_order():
    """block < flag < pass must hold."""
    import pytest

    with pytest.raises(ValueError):
        ThresholdConfig(pass_threshold=0.3, flag_threshold=0.5, block_threshold=0.8)


def test_step_record_creation():
    step = StepRecord(
        step_type="tool_call",
        name="query_database",
        input={"query": "SELECT *"},
        output={"rows": 5},
        duration_ms=120,
    )
    assert step.step_type == "tool_call"
    assert step.duration_ms == 120


def test_execution_event_creation():
    event = ExecutionEvent(
        agent_id="support-bot",
        input={"query": "billing question"},
        output={"response": "Your bill is $50"},
        task="Answer customer billing questions",
    )
    assert event.agent_id == "support-bot"
    assert event.execution_id is not None
    assert event.timestamp is not None
    assert event.latency_ms is None  # set later


def test_execution_event_auto_generates_execution_id():
    event1 = ExecutionEvent(agent_id="a", input={}, output={})
    event2 = ExecutionEvent(agent_id="a", input={}, output={})
    assert event1.execution_id != event2.execution_id


def test_execution_event_with_cost_estimate():
    event = ExecutionEvent(
        agent_id="billing-bot",
        input={"query": "invoice"},
        output={"response": "Here is your invoice"},
        token_count=450,
        cost_estimate=0.0009,
    )
    assert event.token_count == 450
    assert event.cost_estimate == 0.0009


def test_execution_event_cost_estimate_defaults_none():
    event = ExecutionEvent(agent_id="a", input={}, output={})
    assert event.cost_estimate is None


def test_execution_event_session_fields():
    event = ExecutionEvent(
        agent_id="a",
        input="x",
        output="y",
        session_id="sess-1",
        parent_execution_id="parent-1",
        sequence_number=3,
    )
    assert event.session_id == "sess-1"
    assert event.parent_execution_id == "parent-1"
    assert event.sequence_number == 3


def test_execution_event_session_fields_default_none():
    event = ExecutionEvent(agent_id="a", input="x", output="y")
    assert event.session_id is None
    assert event.parent_execution_id is None
    assert event.sequence_number is None


def test_conversation_turn_model():
    turn = ConversationTurn(
        sequence_number=0,
        input="What is revenue?",
        output="Revenue is $5.2B.",
        task="financial Q&A",
    )
    assert turn.sequence_number == 0
    assert turn.input == "What is revenue?"
    assert turn.output == "Revenue is $5.2B."
    assert turn.task == "financial Q&A"


def test_execution_event_with_conversation_history():
    history = [
        ConversationTurn(sequence_number=0, input="hi", output="hello"),
        ConversationTurn(sequence_number=1, input="q", output="a"),
    ]
    event = ExecutionEvent(
        agent_id="bot",
        input="next",
        output="reply",
        conversation_history=history,
    )
    assert event.conversation_history is not None
    assert len(event.conversation_history) == 2
    assert event.conversation_history[0].sequence_number == 0


def test_execution_event_backward_compat_without_history():
    event = ExecutionEvent(agent_id="bot", input="x", output="y")
    assert event.conversation_history is None


def test_vex_result_creation():
    result = VexResult(
        output={"response": "answer"},
        confidence=0.92,
        action="pass",
        execution_id="exec-123",
    )
    assert result.confidence == 0.92
    assert result.action == "pass"
    assert result.corrections is None


def test_vex_result_with_corrections():
    result = VexResult(
        output={"response": "corrected"},
        confidence=0.78,
        action="flag",
        execution_id="exec-456",
        corrections=[{"layer": 1, "action": "repair"}],
    )
    assert len(result.corrections) == 1


# --- Correction fields on VexResult ---


def test_vex_result_with_correction_fields():
    result = VexResult(
        output="corrected output",
        confidence=0.9,
        action="pass",
        execution_id="exec-123",
        corrected=True,
        original_output="bad output",
        corrections=[{"layer": 1, "success": True}],
    )
    assert result.corrected is True
    assert result.original_output == "bad output"


def test_vex_result_backward_compat():
    result = VexResult(
        output="output",
        execution_id="exec-456",
    )
    assert result.corrected is False
    assert result.original_output is None
