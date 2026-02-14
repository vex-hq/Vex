"""Tests for the Vex client: watch decorator, trace context manager, run wrapper."""

import time
from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx

from vex import Vex, VexBlockError, ConfigurationError, ConversationTurn, VexConfig, VexResult
from vex.models import ThresholdConfig


@pytest.fixture
def guard():
    g = Vex(
        api_key="ag_test_key",
        config=VexConfig(
            mode="async",
            api_url="https://api.tryvex.dev",
        ),
    )
    yield g
    g.close()


def test_guard_creation(guard):
    assert guard.api_key == "ag_test_key"
    assert guard.config.mode == "async"


def test_guard_init_does_not_store_event_loop():
    """Vex constructor should not store an event loop on self."""
    guard = Vex(api_key="test-key-1234567890")
    assert not hasattr(guard, "_loop"), "Vex should not store _loop on self"
    guard.close()


def test_guard_rejects_empty_api_key():
    with pytest.raises(ConfigurationError, match="cannot be empty"):
        Vex(api_key="")


def test_guard_rejects_whitespace_api_key():
    with pytest.raises(ConfigurationError, match="cannot be empty"):
        Vex(api_key="   ")


def test_guard_rejects_short_api_key():
    with pytest.raises(ConfigurationError, match="too short"):
        Vex(api_key="abc")


def test_guard_strips_whitespace_from_api_key():
    guard = Vex(api_key="  test-key-1234567890  ")
    assert guard.api_key == "test-key-1234567890"
    guard.close()


def test_default_config_does_not_log_event_ids():
    guard = Vex(api_key="test-key-1234567890", config=VexConfig(mode="async"))
    assert guard.config.log_event_ids is False
    guard.close()


@respx.mock
def test_guard_watch_decorator_async_mode():
    route = respx.post("https://api.tryvex.dev/v1/ingest/batch").mock(
        return_value=httpx.Response(202, json={"accepted": 1})
    )

    guard = Vex(
        api_key="ag_test_key",
        config=VexConfig(
            mode="async",
            api_url="https://api.tryvex.dev",
        ),
    )

    @guard.watch(agent_id="test-bot", task="answer questions")
    def my_agent(query: str) -> str:
        return f"Answer to: {query}"

    result = my_agent("What is 2+2?")
    assert result.output == "Answer to: What is 2+2?"
    assert result.action == "pass"
    assert result.execution_id is not None
    guard.close()


@respx.mock
def test_guard_watch_captures_latency():
    respx.post("https://api.tryvex.dev/v1/ingest/batch").mock(
        return_value=httpx.Response(202, json={"accepted": 1})
    )

    guard = Vex(
        api_key="ag_test_key",
        config=VexConfig(
            mode="async",
            api_url="https://api.tryvex.dev",
        ),
    )

    @guard.watch(agent_id="slow-bot")
    def slow_agent(query: str) -> str:
        time.sleep(0.05)
        return "done"

    result = slow_agent("test")
    assert result.output == "done"
    guard.close()


@respx.mock
def test_guard_watch_handles_agent_exception():
    respx.post("https://api.tryvex.dev/v1/ingest/batch").mock(
        return_value=httpx.Response(202)
    )

    guard = Vex(
        api_key="ag_test_key",
        config=VexConfig(
            mode="async",
            api_url="https://api.tryvex.dev",
        ),
    )

    @guard.watch(agent_id="failing-bot")
    def failing_agent(query: str) -> str:
        raise ValueError("Agent broke")

    with pytest.raises(ValueError, match="Agent broke"):
        failing_agent("test")
    guard.close()


@respx.mock
def test_guard_run_explicit():
    respx.post("https://api.tryvex.dev/v1/ingest/batch").mock(
        return_value=httpx.Response(202, json={"accepted": 1})
    )

    guard = Vex(
        api_key="ag_test_key",
        config=VexConfig(
            mode="async",
            api_url="https://api.tryvex.dev",
        ),
    )

    result = guard.run(
        agent_id="report-gen",
        task="Generate report",
        fn=lambda: {"report": "Q4 summary"},
    )
    assert result.output == {"report": "Q4 summary"}
    assert result.action == "pass"
    guard.close()


@respx.mock
def test_guard_trace_context_manager():
    respx.post("https://api.tryvex.dev/v1/ingest/batch").mock(
        return_value=httpx.Response(202, json={"accepted": 1})
    )

    guard = Vex(
        api_key="ag_test_key",
        config=VexConfig(
            mode="async",
            api_url="https://api.tryvex.dev",
        ),
    )

    with guard.trace(agent_id="enricher", task="Enrich records") as trace:
        output = {"company": "ACME", "revenue": 1000000}
        trace.set_ground_truth({"source": "database"})
        trace.set_schema({"type": "object", "required": ["company", "revenue"]})
        trace.record(output)

    result = trace.result
    assert result.output == output
    assert result.action == "pass"
    guard.close()


@respx.mock
def test_guard_sync_mode():
    respx.post("https://api.tryvex.dev/v1/verify").mock(
        return_value=httpx.Response(200, json={
            "execution_id": "exec-123",
            "confidence": 0.92,
            "action": "pass",
            "output": "verified answer",
            "corrections": None,
            "checks": {},
        })
    )

    guard = Vex(
        api_key="ag_test_key",
        config=VexConfig(
            mode="sync",
            api_url="https://api.tryvex.dev",
        ),
    )

    @guard.watch(agent_id="critical-bot", task="critical task")
    def critical_agent(query: str) -> str:
        return "raw answer"

    result = critical_agent("test")
    assert result.confidence == 0.92
    assert result.action == "pass"
    guard.close()


@respx.mock
def test_guard_trace_with_steps():
    """TraceContext.step() should record intermediate steps in the event."""
    respx.post("https://api.tryvex.dev/v1/ingest/batch").mock(
        return_value=httpx.Response(202, json={"accepted": 1})
    )

    guard = Vex(
        api_key="ag_test_key",
        config=VexConfig(
            mode="async",
            api_url="https://api.tryvex.dev",
        ),
    )

    with guard.trace(agent_id="multi-step", task="pipeline") as trace:
        trace.step(step_type="llm", name="generate", input="prompt", output="text", duration_ms=100.0)
        trace.step(step_type="tool_call", name="search", input="query", output="results", duration_ms=50.0)
        trace.record({"final": "output"})

    assert trace.result.output == {"final": "output"}
    assert trace.result.action == "pass"
    guard.close()


@respx.mock
def test_guard_run_with_ground_truth_and_schema():
    """run() should forward ground_truth and schema to the event."""
    respx.post("https://api.tryvex.dev/v1/ingest/batch").mock(
        return_value=httpx.Response(202, json={"accepted": 1})
    )

    guard = Vex(
        api_key="ag_test_key",
        config=VexConfig(
            mode="async",
            api_url="https://api.tryvex.dev",
        ),
    )

    result = guard.run(
        agent_id="report-gen",
        task="Generate report",
        fn=lambda: {"report": "Q4 summary"},
        ground_truth={"expected": "data"},
        schema={"type": "object"},
    )
    assert result.output == {"report": "Q4 summary"}
    assert result.action == "pass"
    guard.close()


@respx.mock
def test_guard_sync_mode_verify_failure_falls_through():
    """When sync verify fails (HTTP error), should log warning and return pass-through."""
    respx.post("https://api.tryvex.dev/v1/verify").mock(
        return_value=httpx.Response(500, json={"error": "internal"})
    )

    guard = Vex(
        api_key="ag_test_key",
        config=VexConfig(
            mode="sync",
            api_url="https://api.tryvex.dev",
        ),
    )

    @guard.watch(agent_id="critical-bot", task="critical task")
    def critical_agent(query: str) -> str:
        return "raw answer"

    result = critical_agent("test")
    # Should fall through with the original output and pass action
    assert result.output == "raw answer"
    assert result.action == "pass"
    guard.close()


@respx.mock
def test_guard_trace_set_token_count_and_cost():
    """TraceContext.set_token_count() and set_cost_estimate() should flow through to the event."""
    respx.post("https://api.tryvex.dev/v1/ingest/batch").mock(
        return_value=httpx.Response(202, json={"accepted": 1})
    )

    guard = Vex(
        api_key="ag_test_key",
        config=VexConfig(
            mode="async",
            api_url="https://api.tryvex.dev",
        ),
    )

    with guard.trace(agent_id="token-bot", task="token tracking") as trace:
        trace.set_token_count(500)
        trace.set_cost_estimate(0.001)
        trace.record({"summary": "done"})

    assert trace.result.output == {"summary": "done"}
    assert trace.result.action == "pass"
    guard.close()


@respx.mock
def test_guard_trace_set_metadata():
    """TraceContext.set_metadata() should add key-value pairs to event metadata."""
    respx.post("https://api.tryvex.dev/v1/ingest/batch").mock(
        return_value=httpx.Response(202, json={"accepted": 1})
    )

    guard = Vex(
        api_key="ag_test_key",
        config=VexConfig(
            mode="async",
            api_url="https://api.tryvex.dev",
        ),
    )

    with guard.trace(agent_id="meta-bot", task="metadata test") as trace:
        trace.set_metadata("model", "gpt-4")
        trace.set_metadata("temperature", 0.7)
        trace.record({"result": "ok"})

    assert trace.result.output == {"result": "ok"}
    guard.close()


def test_session_auto_generates_id(guard):
    session = guard.session(agent_id="test-agent")
    assert session.session_id is not None
    assert len(session.session_id) == 36  # UUID format


def test_session_uses_provided_id(guard):
    session = guard.session(agent_id="test-agent", session_id="custom-id")
    assert session.session_id == "custom-id"


def test_session_trace_injects_session_fields(guard):
    session = guard.session(agent_id="test-agent")
    with session.trace(task="turn 1", input_data="hello") as ctx:
        ctx.record("world")
    assert ctx.result is not None
    assert session.sequence == 1


def test_session_auto_increments_sequence(guard):
    session = guard.session(agent_id="test-agent")
    with session.trace(task="turn 1", input_data="a") as ctx:
        ctx.record("b")
    with session.trace(task="turn 2", input_data="c") as ctx:
        ctx.record("d")
    assert session.sequence == 2


def test_session_trace_with_parent_execution_id(guard):
    session = guard.session(agent_id="test-agent")
    with session.trace(task="parent") as parent_ctx:
        parent_ctx.record("parent output")
    parent_id = parent_ctx.result.execution_id
    with session.trace(task="child", parent_execution_id=parent_id) as child_ctx:
        child_ctx.record("child output")
    assert session.sequence == 2


def test_session_metadata_merged_into_traces(guard):
    session = guard.session(agent_id="test-agent", metadata={"mode": "chat"})
    with session.trace(task="turn 1", input_data="x") as ctx:
        ctx.record("y")
    # Session metadata should be accessible via the internal state
    assert ctx._metadata.get("mode") == "chat"


def test_session_trace_metadata_overrides_session(guard):
    session = guard.session(agent_id="test-agent", metadata={"mode": "chat"})
    with session.trace(task="turn 1", input_data="x") as ctx:
        ctx.set_metadata("mode", "override")
        ctx.record("y")
    assert ctx._metadata["mode"] == "override"


def test_guard_close_is_idempotent():
    """Calling close() multiple times should not raise."""
    guard = Vex(
        api_key="ag_test_key",
        config=VexConfig(
            mode="async",
            api_url="https://api.tryvex.dev",
        ),
    )
    guard.close()
    guard.close()  # should not raise


@respx.mock
def test_guard_sync_mode_block_raises():
    """When sync verify returns action=block, should raise VexBlockError."""
    respx.post("https://api.tryvex.dev/v1/verify").mock(
        return_value=httpx.Response(200, json={
            "execution_id": "exec-block",
            "confidence": 0.2,
            "action": "block",
            "output": "blocked output",
            "corrections": None,
            "checks": {},
        })
    )

    guard = Vex(
        api_key="ag_test_key",
        config=VexConfig(
            mode="sync",
            api_url="https://api.tryvex.dev",
        ),
    )

    @guard.watch(agent_id="critical-bot", task="critical task")
    def critical_agent(query: str) -> str:
        return "raw answer"

    with pytest.raises(VexBlockError) as exc_info:
        critical_agent("test")

    assert exc_info.value.result.action == "block"
    assert exc_info.value.result.confidence == 0.2
    guard.close()


@respx.mock
def test_guard_sync_mode_flag_returns_normally():
    """When sync verify returns action=flag, should log warning and return normally."""
    respx.post("https://api.tryvex.dev/v1/verify").mock(
        return_value=httpx.Response(200, json={
            "execution_id": "exec-flag",
            "confidence": 0.6,
            "action": "flag",
            "output": "flagged output",
            "corrections": None,
            "checks": {},
        })
    )

    guard = Vex(
        api_key="ag_test_key",
        config=VexConfig(
            mode="sync",
            api_url="https://api.tryvex.dev",
        ),
    )

    @guard.watch(agent_id="critical-bot", task="critical task")
    def critical_agent(query: str) -> str:
        return "raw answer"

    result = critical_agent("test")
    assert result.action == "flag"
    assert result.confidence == 0.6
    guard.close()


@respx.mock
def test_guard_sync_mode_pass_returns_normally():
    """When sync verify returns action=pass, should return normally."""
    respx.post("https://api.tryvex.dev/v1/verify").mock(
        return_value=httpx.Response(200, json={
            "execution_id": "exec-pass",
            "confidence": 0.95,
            "action": "pass",
            "output": "good output",
            "corrections": None,
            "checks": {},
        })
    )

    guard = Vex(
        api_key="ag_test_key",
        config=VexConfig(
            mode="sync",
            api_url="https://api.tryvex.dev",
        ),
    )

    @guard.watch(agent_id="critical-bot", task="critical task")
    def critical_agent(query: str) -> str:
        return "raw answer"

    result = critical_agent("test")
    assert result.action == "pass"
    assert result.confidence == 0.95
    guard.close()


@respx.mock
def test_guard_sync_mode_threshold_config_sent():
    """Verify that threshold config is included in verify request payload."""
    route = respx.post("https://api.tryvex.dev/v1/verify").mock(
        return_value=httpx.Response(200, json={
            "execution_id": "exec-thresh",
            "confidence": 0.9,
            "action": "pass",
            "output": "answer",
            "corrections": None,
            "checks": {},
        })
    )

    guard = Vex(
        api_key="ag_test_key",
        config=VexConfig(
            mode="sync",
            api_url="https://api.tryvex.dev",
            confidence_threshold=ThresholdConfig(
                pass_threshold=0.9,
                flag_threshold=0.6,
                block_threshold=0.3,
            ),
        ),
    )

    @guard.watch(agent_id="thresh-bot", task="threshold test")
    def my_agent(query: str) -> str:
        return "answer"

    my_agent("test")

    # Check that the request payload includes thresholds in metadata
    request = route.calls[0].request
    import json
    body = json.loads(request.content)
    assert "metadata" in body
    assert "thresholds" in body["metadata"]
    assert body["metadata"]["thresholds"]["pass_threshold"] == 0.9
    assert body["metadata"]["thresholds"]["flag_threshold"] == 0.6
    guard.close()


@respx.mock
def test_guard_async_mode_never_raises_block():
    """Async mode should never raise VexBlockError — events are fire-and-forget."""
    respx.post("https://api.tryvex.dev/v1/ingest/batch").mock(
        return_value=httpx.Response(202, json={"accepted": 1})
    )

    guard = Vex(
        api_key="ag_test_key",
        config=VexConfig(
            mode="async",
            api_url="https://api.tryvex.dev",
        ),
    )

    @guard.watch(agent_id="async-bot", task="async task")
    def my_agent(query: str) -> str:
        return "answer"

    # Should never raise, always returns pass
    result = my_agent("test")
    assert result.action == "pass"
    guard.close()


@respx.mock
def test_guard_sync_trace_block_raises():
    """trace() in sync mode should also raise on block."""
    respx.post("https://api.tryvex.dev/v1/verify").mock(
        return_value=httpx.Response(200, json={
            "execution_id": "exec-trace-block",
            "confidence": 0.1,
            "action": "block",
            "output": "blocked",
            "corrections": None,
            "checks": {},
        })
    )

    guard = Vex(
        api_key="ag_test_key",
        config=VexConfig(
            mode="sync",
            api_url="https://api.tryvex.dev",
        ),
    )

    with pytest.raises(VexBlockError):
        with guard.trace(agent_id="trace-bot", task="trace task") as trace:
            trace.record("bad output")

    guard.close()


# --- Conversation history accumulation tests ---


def test_session_accumulates_history_after_three_turns(guard):
    """Session should accumulate conversation turns in _history."""
    session = guard.session(agent_id="chat-bot")

    with session.trace(task="turn 0", input_data="q0") as ctx:
        ctx.record("a0")
    with session.trace(task="turn 1", input_data="q1") as ctx:
        ctx.record("a1")
    with session.trace(task="turn 2", input_data="q2") as ctx:
        ctx.record("a2")

    assert len(session._history) == 3
    assert session._history[0].sequence_number == 0
    assert session._history[0].input == "q0"
    assert session._history[0].output == "a0"
    assert session._history[0].task == "turn 0"
    assert session._history[1].sequence_number == 1
    assert session._history[2].sequence_number == 2


def test_session_window_size_limits_history():
    """Window size should limit the number of turns kept in _history."""
    guard = Vex(
        api_key="ag_test_key",
        config=VexConfig(
            mode="async",
            api_url="https://api.tryvex.dev",
            conversation_window_size=2,
        ),
    )

    session = guard.session(agent_id="chat-bot")

    for i in range(5):
        with session.trace(task=f"turn {i}", input_data=f"q{i}") as ctx:
            ctx.record(f"a{i}")

    # Only last 2 turns should be kept
    assert len(session._history) == 2
    assert session._history[0].sequence_number == 3
    assert session._history[1].sequence_number == 4
    guard.close()


def test_non_session_trace_has_none_history(guard):
    """Non-session traces (guard.trace) should have None conversation_history."""
    with guard.trace(agent_id="one-shot", task="task") as ctx:
        ctx.record("output")

    assert ctx._conversation_history is None


def test_session_history_snapshot_excludes_current_turn(guard):
    """The history snapshot passed to TraceContext should NOT include the current turn."""
    session = guard.session(agent_id="chat-bot")

    # Turn 0: no history yet
    with session.trace(task="turn 0", input_data="q0") as ctx0:
        ctx0.record("a0")
    assert ctx0._conversation_history is None  # No prior turns

    # Turn 1: should have turn 0 in history
    with session.trace(task="turn 1", input_data="q1") as ctx1:
        ctx1.record("a1")
    assert ctx1._conversation_history is not None
    assert len(ctx1._conversation_history) == 1
    assert ctx1._conversation_history[0].sequence_number == 0
    assert ctx1._conversation_history[0].output == "a0"

    # Turn 2: should have turns 0 and 1
    with session.trace(task="turn 2", input_data="q2") as ctx2:
        ctx2.record("a2")
    assert ctx2._conversation_history is not None
    assert len(ctx2._conversation_history) == 2


def test_session_turn_data_correctness(guard):
    """Each ConversationTurn should capture the correct sequence_number, input, output, task."""
    session = guard.session(agent_id="chat-bot")

    with session.trace(task="financial Q&A", input_data="What is revenue?") as ctx:
        ctx.record("Revenue is $5.2B.")

    turn = session._history[0]
    assert turn.sequence_number == 0
    assert turn.input == "What is revenue?"
    assert turn.output == "Revenue is $5.2B."
    assert turn.task == "financial Q&A"


# --- Correction integration tests ---


@respx.mock
def test_guard_sync_correction_returns_corrected_output():
    """When server returns corrected=True, VexResult should reflect corrected output."""
    respx.post("https://api.tryvex.dev/v1/verify").mock(
        return_value=httpx.Response(200, json={
            "execution_id": "exec-corrected",
            "confidence": 0.9,
            "action": "pass",
            "output": "corrected answer",
            "checks": {},
            "corrected": True,
            "original_output": "bad answer",
            "correction_attempts": [
                {"layer": 1, "layer_name": "repair", "success": True, "latency_ms": 300},
            ],
        })
    )

    guard = Vex(
        api_key="ag_test_key",
        config=VexConfig(
            mode="sync",
            api_url="https://api.tryvex.dev",
            correction="cascade",
        ),
    )

    @guard.watch(agent_id="bot", task="task")
    def my_agent(q: str) -> str:
        return "bad answer"

    result = my_agent("test")
    assert result.output == "corrected answer"
    assert result.corrected is True
    assert result.action == "pass"
    guard.close()


@respx.mock
def test_guard_sync_correction_opaque_hides_details():
    """Opaque mode: original_output and corrections should be None."""
    respx.post("https://api.tryvex.dev/v1/verify").mock(
        return_value=httpx.Response(200, json={
            "execution_id": "exec-opaque",
            "confidence": 0.9,
            "action": "pass",
            "output": "corrected",
            "checks": {},
            "corrected": True,
            "original_output": None,
            "correction_attempts": None,
        })
    )

    guard = Vex(
        api_key="ag_test_key",
        config=VexConfig(
            mode="sync",
            api_url="https://api.tryvex.dev",
            correction="cascade",
            transparency="opaque",
        ),
    )

    @guard.watch(agent_id="bot", task="task")
    def my_agent(q: str) -> str:
        return "bad"

    result = my_agent("test")
    assert result.corrected is True
    assert result.original_output is None
    assert result.corrections is None
    guard.close()


@respx.mock
def test_guard_sync_correction_transparent_shows_details():
    """Transparent mode: original_output and corrections should be populated."""
    respx.post("https://api.tryvex.dev/v1/verify").mock(
        return_value=httpx.Response(200, json={
            "execution_id": "exec-transparent",
            "confidence": 0.9,
            "action": "pass",
            "output": "corrected",
            "checks": {},
            "corrected": True,
            "original_output": "bad output",
            "correction_attempts": [
                {"layer": 1, "layer_name": "repair", "success": True},
            ],
        })
    )

    guard = Vex(
        api_key="ag_test_key",
        config=VexConfig(
            mode="sync",
            api_url="https://api.tryvex.dev",
            correction="cascade",
            transparency="transparent",
        ),
    )

    @guard.watch(agent_id="bot", task="task")
    def my_agent(q: str) -> str:
        return "bad"

    result = my_agent("test")
    assert result.corrected is True
    assert result.original_output == "bad output"
    assert result.corrections is not None
    assert len(result.corrections) == 1
    guard.close()


@respx.mock
def test_guard_sync_correction_failed_raises_block():
    """When correction fails (all attempts exhausted), should raise VexBlockError."""
    respx.post("https://api.tryvex.dev/v1/verify").mock(
        return_value=httpx.Response(200, json={
            "execution_id": "exec-block",
            "confidence": 0.2,
            "action": "block",
            "output": "bad output",
            "checks": {},
            "corrected": False,
        })
    )

    guard = Vex(
        api_key="ag_test_key",
        config=VexConfig(
            mode="sync",
            api_url="https://api.tryvex.dev",
            correction="cascade",
        ),
    )

    @guard.watch(agent_id="bot", task="task")
    def my_agent(q: str) -> str:
        return "bad"

    with pytest.raises(VexBlockError):
        my_agent("test")
    guard.close()


@respx.mock
def test_guard_async_mode_ignores_correction():
    """Async mode should ignore correction setting -- fire-and-forget."""
    respx.post("https://api.tryvex.dev/v1/ingest/batch").mock(
        return_value=httpx.Response(202, json={"accepted": 1})
    )

    guard = Vex(
        api_key="ag_test_key",
        config=VexConfig(
            mode="async",
            api_url="https://api.tryvex.dev",
            correction="cascade",
        ),
    )

    @guard.watch(agent_id="bot", task="task")
    def my_agent(q: str) -> str:
        return "answer"

    result = my_agent("test")
    assert result.action == "pass"
    assert result.corrected is False
    guard.close()


@respx.mock
def test_guard_sync_no_correction_unchanged():
    """correction=none -> existing behavior, no correction fields."""
    respx.post("https://api.tryvex.dev/v1/verify").mock(
        return_value=httpx.Response(200, json={
            "execution_id": "exec-none",
            "confidence": 0.6,
            "action": "flag",
            "output": "flagged",
            "checks": {},
        })
    )

    guard = Vex(
        api_key="ag_test_key",
        config=VexConfig(
            mode="sync",
            api_url="https://api.tryvex.dev",
            correction="none",
        ),
    )

    @guard.watch(agent_id="bot", task="task")
    def my_agent(q: str) -> str:
        return "answer"

    result = my_agent("test")
    assert result.action == "flag"
    assert result.corrected is False
    guard.close()
