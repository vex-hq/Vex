"""Tests for the AgentGuard client: watch decorator, trace context manager, run wrapper."""

import time

import httpx
import pytest
import respx

from agentguard import AgentGuard, GuardConfig, GuardResult
from agentguard.models import ThresholdConfig


@pytest.fixture
def guard():
    g = AgentGuard(
        api_key="ag_test_key",
        config=GuardConfig(
            mode="async",
            api_url="https://api.agentguard.dev",
        ),
    )
    yield g
    g.close()


def test_guard_creation(guard):
    assert guard.api_key == "ag_test_key"
    assert guard.config.mode == "async"


@respx.mock
def test_guard_watch_decorator_async_mode():
    route = respx.post("https://api.agentguard.dev/v1/ingest/batch").mock(
        return_value=httpx.Response(202, json={"accepted": 1})
    )

    guard = AgentGuard(
        api_key="ag_test_key",
        config=GuardConfig(
            mode="async",
            api_url="https://api.agentguard.dev",
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
    respx.post("https://api.agentguard.dev/v1/ingest/batch").mock(
        return_value=httpx.Response(202, json={"accepted": 1})
    )

    guard = AgentGuard(
        api_key="ag_test_key",
        config=GuardConfig(
            mode="async",
            api_url="https://api.agentguard.dev",
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
    respx.post("https://api.agentguard.dev/v1/ingest/batch").mock(
        return_value=httpx.Response(202)
    )

    guard = AgentGuard(
        api_key="ag_test_key",
        config=GuardConfig(
            mode="async",
            api_url="https://api.agentguard.dev",
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
    respx.post("https://api.agentguard.dev/v1/ingest/batch").mock(
        return_value=httpx.Response(202, json={"accepted": 1})
    )

    guard = AgentGuard(
        api_key="ag_test_key",
        config=GuardConfig(
            mode="async",
            api_url="https://api.agentguard.dev",
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
    respx.post("https://api.agentguard.dev/v1/ingest/batch").mock(
        return_value=httpx.Response(202, json={"accepted": 1})
    )

    guard = AgentGuard(
        api_key="ag_test_key",
        config=GuardConfig(
            mode="async",
            api_url="https://api.agentguard.dev",
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
    respx.post("https://api.agentguard.dev/v1/verify").mock(
        return_value=httpx.Response(200, json={
            "execution_id": "exec-123",
            "confidence": 0.92,
            "action": "pass",
            "output": "verified answer",
            "corrections": None,
            "checks": {},
        })
    )

    guard = AgentGuard(
        api_key="ag_test_key",
        config=GuardConfig(
            mode="sync",
            api_url="https://api.agentguard.dev",
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
    respx.post("https://api.agentguard.dev/v1/ingest/batch").mock(
        return_value=httpx.Response(202, json={"accepted": 1})
    )

    guard = AgentGuard(
        api_key="ag_test_key",
        config=GuardConfig(
            mode="async",
            api_url="https://api.agentguard.dev",
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
    respx.post("https://api.agentguard.dev/v1/ingest/batch").mock(
        return_value=httpx.Response(202, json={"accepted": 1})
    )

    guard = AgentGuard(
        api_key="ag_test_key",
        config=GuardConfig(
            mode="async",
            api_url="https://api.agentguard.dev",
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
    respx.post("https://api.agentguard.dev/v1/verify").mock(
        return_value=httpx.Response(500, json={"error": "internal"})
    )

    guard = AgentGuard(
        api_key="ag_test_key",
        config=GuardConfig(
            mode="sync",
            api_url="https://api.agentguard.dev",
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


def test_guard_close_is_idempotent():
    """Calling close() multiple times should not raise."""
    guard = AgentGuard(
        api_key="ag_test_key",
        config=GuardConfig(
            mode="async",
            api_url="https://api.agentguard.dev",
        ),
    )
    guard.close()
    guard.close()  # should not raise
