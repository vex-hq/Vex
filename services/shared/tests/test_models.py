from shared.models import (
    ConversationTurn,
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


def test_ingest_event_session_fields():
    event = IngestEvent(
        agent_id="a",
        input="x",
        output="y",
        session_id="s1",
        parent_execution_id="p1",
        sequence_number=2,
    )
    assert event.session_id == "s1"
    assert event.parent_execution_id == "p1"
    assert event.sequence_number == 2


def test_ingest_event_session_fields_default_none():
    event = IngestEvent(agent_id="a", input="x", output="y")
    assert event.session_id is None
    assert event.parent_execution_id is None
    assert event.sequence_number is None


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


def test_conversation_turn_creation():
    turn = ConversationTurn(
        sequence_number=0,
        input="What is ACME's revenue?",
        output="ACME's revenue is $5.2B.",
        task="Answer financial questions",
    )
    assert turn.sequence_number == 0
    assert turn.input == "What is ACME's revenue?"
    assert turn.output == "ACME's revenue is $5.2B."
    assert turn.task == "Answer financial questions"


def test_ingest_event_with_conversation_history():
    history = [
        ConversationTurn(sequence_number=0, input="hi", output="hello"),
        ConversationTurn(sequence_number=1, input="q", output="a", task="chat"),
    ]
    event = IngestEvent(
        agent_id="bot-1",
        input="next q",
        output="next a",
        conversation_history=history,
    )
    assert event.conversation_history is not None
    assert len(event.conversation_history) == 2
    assert event.conversation_history[0].sequence_number == 0
    assert event.conversation_history[1].task == "chat"


def test_ingest_event_backward_compat_without_history():
    event = IngestEvent(agent_id="bot-1", input="x", output="y")
    assert event.conversation_history is None


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


# --- Correction response model tests ---


def test_correction_attempt_response_creation():
    from shared.models import CorrectionAttemptResponse
    attempt = CorrectionAttemptResponse(
        layer=1,
        layer_name="repair",
        corrected_output="fixed",
        confidence=0.9,
        action="pass",
        success=True,
        latency_ms=340.0,
    )
    assert attempt.layer == 1
    assert attempt.success is True


def test_verify_response_with_correction_fields():
    from shared.models import VerifyResponse, CorrectionAttemptResponse
    response = VerifyResponse(
        execution_id="exec-123",
        confidence=0.9,
        action="pass",
        output="corrected output",
        corrected=True,
        original_output="bad output",
        correction_attempts=[
            CorrectionAttemptResponse(
                layer=1, layer_name="repair", corrected_output="fixed",
                confidence=0.9, action="pass", success=True, latency_ms=340.0,
            ),
        ],
    )
    assert response.corrected is True
    assert response.original_output == "bad output"
    assert len(response.correction_attempts) == 1


def test_verify_response_backward_compat_no_correction():
    from shared.models import VerifyResponse
    response = VerifyResponse(
        execution_id="exec-456",
        confidence=0.8,
        action="pass",
        output="output",
    )
    assert response.corrected is False
    assert response.original_output is None
    assert response.correction_attempts is None
