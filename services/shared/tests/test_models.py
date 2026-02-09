from shared.models import (
    StepRecord,
    IngestEvent,
    IngestBatchRequest,
    IngestResponse,
    VerifyRequest,
    VerifyResponse,
    CheckResult,
)


def test_step_record_creation():
    step = StepRecord(
        step_type="tool_call",
        name="search",
        input={"query": "test"},
        output={"results": []},
        duration_ms=42.5,
    )
    assert step.step_type == "tool_call"
    assert step.name == "search"
    assert step.input == {"query": "test"}
    assert step.output == {"results": []}
    assert step.duration_ms == 42.5
    assert step.timestamp is not None


def test_step_record_defaults():
    step = StepRecord(step_type="llm_call", name="generate")
    assert step.input is None
    assert step.output is None
    assert step.duration_ms is None
    assert step.timestamp is not None


def test_ingest_event_creation():
    event = IngestEvent(
        agent_id="bot-1",
        input={"query": "test"},
        output={"answer": "result"},
    )
    assert event.agent_id == "bot-1"
    assert event.execution_id is not None


def test_ingest_event_defaults():
    event = IngestEvent(
        agent_id="bot-1",
        input={},
        output={},
    )
    assert event.task is None
    assert event.steps == []
    assert event.token_count is None
    assert event.latency_ms is None
    assert event.ground_truth is None
    assert event.schema_definition is None
    assert event.metadata == {}
    assert event.timestamp is not None


def test_ingest_batch_request():
    events = [
        IngestEvent(agent_id="bot-1", input={}, output={}),
        IngestEvent(agent_id="bot-2", input={}, output={}),
    ]
    batch = IngestBatchRequest(events=events)
    assert len(batch.events) == 2


def test_ingest_response():
    resp = IngestResponse(accepted=5, execution_ids=["a", "b", "c", "d", "e"])
    assert resp.accepted == 5


def test_ingest_response_defaults():
    resp = IngestResponse(accepted=0)
    assert resp.execution_ids == []


def test_verify_request_inherits_ingest_event():
    req = VerifyRequest(agent_id="bot-1", input={}, output={})
    assert req.execution_id is not None
    assert req.agent_id == "bot-1"


def test_verify_request_is_ingest_event():
    req = VerifyRequest(agent_id="bot-1", input={}, output={})
    assert isinstance(req, IngestEvent)


def test_verify_response():
    resp = VerifyResponse(
        execution_id="exec-1",
        confidence=0.85,
        action="pass",
        output={"answer": "verified"},
        corrections=None,
        checks={
            "schema": CheckResult(check_type="schema", score=1.0, passed=True),
        },
    )
    assert resp.action == "pass"
    assert resp.checks["schema"].passed is True


def test_verify_response_defaults():
    resp = VerifyResponse(execution_id="exec-1")
    assert resp.confidence is None
    assert resp.action == "pass"
    assert resp.output is None
    assert resp.corrections is None
    assert resp.checks == {}


def test_check_result():
    cr = CheckResult(
        check_type="hallucination",
        score=0.72,
        passed=True,
        details={"flagged_claims": []},
    )
    assert cr.check_type == "hallucination"
    assert cr.score == 0.72


def test_check_result_defaults():
    cr = CheckResult(check_type="schema", score=1.0, passed=True)
    assert cr.details == {}


def test_ingest_event_serialization_roundtrip():
    event = IngestEvent(
        agent_id="bot-1",
        input={"query": "test"},
        output={"answer": "result"},
        token_count=150,
        latency_ms=320.5,
    )
    json_str = event.model_dump_json()
    restored = IngestEvent.model_validate_json(json_str)
    assert restored.agent_id == event.agent_id
    assert restored.execution_id == event.execution_id
    assert restored.token_count == 150


def test_verify_response_serialization_roundtrip():
    resp = VerifyResponse(
        execution_id="exec-1",
        confidence=0.85,
        action="pass",
        output={"answer": "verified"},
        checks={
            "schema": CheckResult(check_type="schema", score=1.0, passed=True),
        },
    )
    json_str = resp.model_dump_json()
    restored = VerifyResponse.model_validate_json(json_str)
    assert restored.execution_id == resp.execution_id
    assert restored.confidence == 0.85
    assert restored.checks["schema"].passed is True


def test_ingest_event_unique_execution_ids():
    event1 = IngestEvent(agent_id="bot-1", input={}, output={})
    event2 = IngestEvent(agent_id="bot-1", input={}, output={})
    assert event1.execution_id != event2.execution_id


def test_ingest_event_with_steps():
    steps = [
        StepRecord(step_type="llm_call", name="generate", output="Hello"),
        StepRecord(step_type="tool_call", name="search", input="query"),
    ]
    event = IngestEvent(
        agent_id="bot-1",
        input={"query": "test"},
        output={"answer": "result"},
        steps=steps,
    )
    assert len(event.steps) == 2
    assert event.steps[0].step_type == "llm_call"
    assert event.steps[1].name == "search"
