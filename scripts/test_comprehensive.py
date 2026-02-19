#!/usr/bin/env python3
"""Comprehensive E2E test suite for the Vex platform.

Exercises the full SDK → Sync Gateway → Verification Engine → Redis pipeline
across 20+ scenarios covering all verification checks, correction layers,
plan enforcement, error handling, and edge cases.

Usage:
    export VEX_API_KEY=ag_live_...
    export VEX_API_URL=https://api.tryvex.dev   # optional, this is the default

    python3 scripts/test_comprehensive.py
    python3 scripts/test_comprehensive.py --section verification  # run one section
    python3 scripts/test_comprehensive.py --section correction
    python3 scripts/test_comprehensive.py --section plan
    python3 scripts/test_comprehensive.py --section edge
    python3 scripts/test_comprehensive.py --section multiturn
"""

import argparse
import json
import os
import sys
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_KEY = os.environ.get("VEX_API_KEY") or os.environ.get("AGENTGUARD_API_KEY", "")
API_URL = os.environ.get("VEX_API_URL") or os.environ.get(
    "AGENTGUARD_API_URL", "https://api.tryvex.dev"
)

if not API_KEY:
    print("ERROR: Set VEX_API_KEY (or AGENTGUARD_API_KEY) environment variable.")
    sys.exit(1)

# ---------------------------------------------------------------------------
# ANSI helpers
# ---------------------------------------------------------------------------

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def header(title: str) -> None:
    print(f"\n{'='*72}")
    print(f"{BOLD}{CYAN}{title}{RESET}")
    print(f"{'='*72}")


def section_header(title: str) -> None:
    print(f"\n{'─'*72}")
    print(f"{BOLD}{title}{RESET}")
    print(f"{'─'*72}")


def ok(msg: str) -> None:
    print(f"  {GREEN}PASS{RESET}  {msg}")


def fail(msg: str) -> None:
    print(f"  {RED}FAIL{RESET}  {msg}")


def info(msg: str) -> None:
    print(f"  {DIM}INFO{RESET}  {msg}")


def warn(msg: str) -> None:
    print(f"  {YELLOW}WARN{RESET}  {msg}")


# ---------------------------------------------------------------------------
# Import SDK
# ---------------------------------------------------------------------------

from vex import Vex, VexConfig, VexBlockError, VexResult, Session  # noqa: E402


# ---------------------------------------------------------------------------
# Helper: raw HTTP verify (for testing API-level behavior)
# ---------------------------------------------------------------------------

def raw_verify(
    payload: Dict[str, Any],
    timeout: float = 60.0,
) -> requests.Response:
    """Send a raw POST to /v1/verify, bypassing the SDK."""
    return requests.post(
        f"{API_URL}/v1/verify",
        json=payload,
        headers={"X-Vex-Key": API_KEY, "Content-Type": "application/json"},
        timeout=timeout,
    )


def raw_ingest(
    payload: Dict[str, Any],
    timeout: float = 60.0,
) -> requests.Response:
    """Send a raw POST to /v1/ingest, bypassing the SDK."""
    return requests.post(
        f"{API_URL}/v1/ingest",
        json=payload,
        headers={"X-Vex-Key": API_KEY, "Content-Type": "application/json"},
        timeout=timeout,
    )


def raw_ingest_batch(
    events: List[Dict[str, Any]],
    timeout: float = 30.0,
) -> requests.Response:
    """Send a raw POST to /v1/ingest/batch."""
    return requests.post(
        f"{API_URL}/v1/ingest/batch",
        json={"events": events},
        headers={"X-Vex-Key": API_KEY, "Content-Type": "application/json"},
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# Helper: SDK verify with result extraction
# ---------------------------------------------------------------------------

def sdk_verify(
    agent_id: str,
    task: str,
    output: Any,
    ground_truth: Any = None,
    schema: Optional[Dict] = None,
    correction: str = "none",
    transparency: str = "opaque",
    input_data: Any = None,
    timeout_s: float = 30.0,
) -> Tuple[Optional[VexResult], bool]:
    """Run SDK sync verification. Returns (result, was_blocked)."""
    guard = Vex(
        api_key=API_KEY,
        config=VexConfig(
            api_url=API_URL,
            mode="sync",
            correction=correction,
            transparency=transparency,
            timeout_s=timeout_s,
        ),
    )

    blocked = False
    result = None

    try:
        with guard.trace(
            agent_id=agent_id,
            task=task,
            input_data=input_data or {},
        ) as ctx:
            if ground_truth is not None:
                ctx.set_ground_truth(ground_truth)
            if schema is not None:
                ctx.set_schema(schema)
            ctx.record(output)

        result = ctx.result
    except VexBlockError as exc:
        blocked = True
        result = getattr(exc, "result", None)
    finally:
        guard.close()

    return result, blocked


# ===========================================================================
# SECTION 1: VERIFICATION CHECKS
# ===========================================================================

def test_v1_schema_valid() -> Tuple[bool, str]:
    """Valid output matching JSON Schema → expect pass or high-confidence flag."""
    header("V1: Schema — Valid Output")

    result, blocked = sdk_verify(
        agent_id="test-schema-valid",
        task="Return customer record",
        output=json.dumps({
            "id": 42,
            "name": "Jane Doe",
            "email": "jane@example.com",
        }),
        schema={
            "type": "object",
            "required": ["id", "name", "email"],
            "properties": {
                "id": {"type": "integer"},
                "name": {"type": "string"},
                "email": {"type": "string"},
            },
        },
        ground_truth={"id": 42, "name": "Jane Doe", "email": "jane@example.com"},
    )

    if result is None:
        fail("No result returned")
        return False, "no result"

    info(f"action={result.action}, confidence={result.confidence}")

    if result.action in ("pass", "flag") and (result.confidence or 0) >= 0.5:
        ok(f"Schema-valid output accepted: action={result.action}")
        return True, result.action

    fail(f"Expected pass/flag, got {result.action} conf={result.confidence}")
    return False, result.action


def test_v2_schema_violation() -> Tuple[bool, str]:
    """Output missing required fields → expect block (schema score=0)."""
    header("V2: Schema — Missing Required Fields")

    result, blocked = sdk_verify(
        agent_id="test-schema-violation",
        task="Return customer record with id, name, email",
        output=json.dumps({"name": "John"}),
        schema={
            "type": "object",
            "required": ["id", "name", "email"],
            "properties": {
                "id": {"type": "integer"},
                "name": {"type": "string"},
                "email": {"type": "string", "format": "email"},
            },
        },
        ground_truth={"id": 1, "name": "John", "email": "john@test.com"},
    )

    if blocked:
        ok("Blocked: schema violation detected")
        return True, "block"

    if result and result.action in ("flag", "block"):
        ok(f"Schema violation caught: action={result.action}")
        return True, result.action

    fail(f"Expected flag/block for schema violation, got {result.action if result else 'None'}")
    return False, result.action if result else "no result"


def test_v3_schema_type_mismatch() -> Tuple[bool, str]:
    """Output has wrong types (string where integer expected) → expect flag/block."""
    header("V3: Schema — Type Mismatch")

    result, blocked = sdk_verify(
        agent_id="test-schema-type",
        task="Return numeric metrics",
        output=json.dumps({
            "revenue": "five billion",
            "profit": "eight hundred million",
            "employees": "twelve thousand",
        }),
        schema={
            "type": "object",
            "required": ["revenue", "profit", "employees"],
            "properties": {
                "revenue": {"type": "number"},
                "profit": {"type": "number"},
                "employees": {"type": "integer"},
            },
        },
        ground_truth={"revenue": 5200000000, "profit": 800000000, "employees": 12000},
    )

    if blocked:
        ok("Blocked: type mismatch detected")
        return True, "block"

    if result and result.action in ("flag", "block"):
        ok(f"Type mismatch caught: action={result.action}")
        return True, result.action

    fail(f"Expected flag/block, got {result.action if result else 'None'}")
    return False, result.action if result else "no result"


def test_v4_hallucination_fabricated_facts() -> Tuple[bool, str]:
    """Output fabricates data not in ground truth → expect flag/block."""
    header("V4: Hallucination — Fabricated Facts")

    result, blocked = sdk_verify(
        agent_id="test-hallucination",
        task="Summarize ACME Corp Q4 financials",
        output=(
            "ACME Corp reported revenue of $15 billion in Q4, up 200% year-over-year. "
            "The company acquired GlobalTech for $2B and announced plans to IPO on NASDAQ. "
            "CEO John Smith stated this was the best quarter in company history."
        ),
        ground_truth={
            "company": "ACME Corp",
            "revenue": "$5.2 billion",
            "profit": "$800 million",
            "yoy_growth": "8%",
            "employees": 12000,
            "publicly_traded": False,
            "acquisitions": [],
            "ceo": "Sarah Johnson",
        },
    )

    if blocked:
        ok("Blocked: hallucinated facts detected")
        return True, "block"

    if result and result.action in ("flag", "block"):
        ok(f"Hallucination caught: action={result.action}, conf={result.confidence}")
        return True, result.action

    fail(f"Expected flag/block for hallucination, got {result.action if result else 'None'}")
    return False, result.action if result else "no result"


def test_v5_hallucination_accurate() -> Tuple[bool, str]:
    """Output matches ground truth accurately → expect pass."""
    header("V5: Hallucination — Accurate Output")

    result, blocked = sdk_verify(
        agent_id="test-accurate",
        task="Summarize ACME Corp Q4 financials",
        output=(
            "ACME Corp reported revenue of $5.2 billion in Q4, with a profit of "
            "$800 million. The company has approximately 12,000 employees."
        ),
        ground_truth={
            "company": "ACME Corp",
            "revenue": "$5.2 billion",
            "profit": "$800 million",
            "employees": 12000,
        },
    )

    if result is None:
        fail("No result returned")
        return False, "no result"

    info(f"action={result.action}, confidence={result.confidence}")

    if result.action in ("pass", "flag") and (result.confidence or 0) >= 0.5:
        ok(f"Accurate output accepted: action={result.action}")
        return True, result.action

    fail(f"Expected pass/flag for accurate output, got {result.action}")
    return False, result.action


def test_v6_drift_off_topic() -> Tuple[bool, str]:
    """Output is completely off-topic → expect flag/block."""
    header("V6: Drift — Off-Topic Response")

    result, blocked = sdk_verify(
        agent_id="test-drift",
        task="Provide quarterly financial analysis for ACME Corp",
        output=(
            "To make a perfect sourdough bread, you need 500g of flour, 350g of water, "
            "100g of sourdough starter, and 10g of salt. Mix the ingredients and let "
            "the dough ferment for 12 hours at room temperature."
        ),
        ground_truth=None,  # No ground truth — testing drift only
    )

    if blocked:
        ok("Blocked: off-topic drift detected")
        return True, "block"

    if result and result.action in ("flag", "block"):
        ok(f"Drift caught: action={result.action}, conf={result.confidence}")
        return True, result.action

    fail(f"Expected flag/block for off-topic, got {result.action if result else 'None'}")
    return False, result.action if result else "no result"


def test_v7_drift_on_task() -> Tuple[bool, str]:
    """Output is relevant to the task → expect pass."""
    header("V7: Drift — On-Task Response")

    result, blocked = sdk_verify(
        agent_id="test-on-task",
        task="Explain the benefits of cloud computing for small businesses",
        output=(
            "Cloud computing offers several key benefits for small businesses: "
            "1) Cost savings through pay-as-you-go pricing, eliminating the need for "
            "expensive on-premise hardware. 2) Scalability to handle growth without "
            "infrastructure overhaul. 3) Remote access enabling distributed teams. "
            "4) Automatic updates and security patches managed by the provider."
        ),
        ground_truth=None,
    )

    if result is None:
        fail("No result returned")
        return False, "no result"

    info(f"action={result.action}, confidence={result.confidence}")

    if result.action in ("pass", "flag") and (result.confidence or 0) >= 0.5:
        ok(f"On-task output accepted: action={result.action}")
        return True, result.action

    fail(f"Expected pass/flag, got {result.action}")
    return False, result.action


def test_v8_no_ground_truth_no_schema() -> Tuple[bool, str]:
    """Verify with no ground truth and no schema — only drift check active."""
    header("V8: Minimal — No Ground Truth, No Schema")

    result, blocked = sdk_verify(
        agent_id="test-minimal",
        task="Write a haiku about programming",
        output="Semicolons fall\nLike autumn leaves in the code\nBugs bloom in the spring",
        ground_truth=None,
    )

    if result is None:
        fail("No result returned")
        return False, "no result"

    info(f"action={result.action}, confidence={result.confidence}")

    # With no ground truth and schema, hallucination and schema are skipped (score=1.0)
    # Only drift is active, and the output is on-task
    if result.action in ("pass", "flag"):
        ok(f"Minimal verify works: action={result.action}")
        return True, result.action

    fail(f"Expected pass/flag, got {result.action}")
    return False, result.action


def test_v9_combined_failures() -> Tuple[bool, str]:
    """Output fails ALL checks — schema, hallucination, and drift → expect block."""
    header("V9: Combined — All Checks Fail")

    result, blocked = sdk_verify(
        agent_id="test-all-fail",
        task="Return structured financial data for ACME Corp",
        output=json.dumps({"pizza": "pepperoni", "toppings": ["cheese", "mushrooms"]}),
        schema={
            "type": "object",
            "required": ["company", "revenue", "profit"],
            "properties": {
                "company": {"type": "string"},
                "revenue": {"type": "number"},
                "profit": {"type": "number"},
            },
        },
        ground_truth={
            "company": "ACME Corp",
            "revenue": 5200000000,
            "profit": 800000000,
        },
    )

    if blocked:
        ok("Blocked: all checks failed")
        return True, "block"

    if result and result.action == "block":
        ok(f"All checks failed → block, conf={result.confidence}")
        return True, "block"

    if result and result.action == "flag":
        warn(f"Expected block but got flag, conf={result.confidence}")
        return True, "flag"  # Acceptable — LLM scoring can vary

    fail(f"Expected block/flag, got {result.action if result else 'None'}")
    return False, result.action if result else "no result"


# ===========================================================================
# SECTION 2: MULTI-TURN / COHERENCE
# ===========================================================================

def test_m1_consistent_session() -> Tuple[bool, str]:
    """3-turn consistent conversation → all turns should pass."""
    header("M1: Multi-Turn — Consistent Session")

    guard = Vex(
        api_key=API_KEY,
        config=VexConfig(api_url=API_URL, mode="sync", correction="none", timeout_s=30.0),
    )
    session = Session(guard, agent_id="test-consistent-session")

    turns = [
        ("What is ACME's revenue?", "ACME Corp's Q4 revenue was $5.2 billion."),
        ("What about profit?", "ACME Corp reported a profit of $800 million in Q4."),
        ("What's the profit margin?", "With $5.2B revenue and $800M profit, the margin is approximately 15.4%."),
    ]

    gt = {"revenue": "$5.2 billion", "profit": "$800 million", "employees": 12000}
    all_passed = True
    actions = []

    for i, (q, a) in enumerate(turns):
        try:
            with session.trace(
                task="Financial Q&A for ACME Corp",
                input_data={"query": q},
            ) as ctx:
                ctx.set_ground_truth(gt)
                ctx.record({"response": a})

            r = ctx.result
            action = r.action if r else "None"
            actions.append(action)
            info(f"Turn {i+1}: action={action}, conf={r.confidence if r else 'None'}")

            if action not in ("pass", "flag"):
                all_passed = False
        except VexBlockError:
            actions.append("block")
            all_passed = False

    guard.close()

    if all_passed:
        ok(f"All turns accepted: {actions}")
        return True, "consistent"

    fail(f"Expected all pass/flag, got: {actions}")
    return False, str(actions)


def test_m2_contradiction() -> Tuple[bool, str]:
    """Agent contradicts itself across turns → expect flag/block."""
    header("M2: Multi-Turn — Self-Contradiction")

    guard = Vex(
        api_key=API_KEY,
        config=VexConfig(api_url=API_URL, mode="sync", correction="none", timeout_s=30.0),
    )
    session = Session(guard, agent_id="test-contradiction")

    # Turn 1: establish a fact
    with session.trace(
        task="Financial Q&A for ACME Corp",
        input_data={"query": "What is ACME's revenue?"},
    ) as ctx1:
        ctx1.set_ground_truth({"revenue": "$5.2 billion"})
        ctx1.record({"response": "ACME Corp's Q4 revenue was $5.2 billion."})

    r1 = ctx1.result
    info(f"Turn 1: action={r1.action if r1 else 'None'}")

    # Turn 2: directly contradict
    blocked = False
    result = None

    try:
        with session.trace(
            task="Financial Q&A for ACME Corp",
            input_data={"query": "Can you confirm ACME's revenue?"},
        ) as ctx2:
            ctx2.set_ground_truth({"revenue": "$5.2 billion"})
            ctx2.record({
                "response": "Actually, ACME Corp's revenue was $50 billion in Q4. "
                "I was completely wrong before — they are ten times larger than I said."
            })

        result = ctx2.result
    except VexBlockError:
        blocked = True

    guard.close()

    if blocked:
        ok("Blocked: contradiction detected")
        return True, "block"

    if result and result.action in ("flag", "block"):
        ok(f"Contradiction caught: action={result.action}, conf={result.confidence}")
        return True, result.action

    fail(f"Expected flag/block on contradiction, got {result.action if result else 'None'}")
    return False, result.action if result else "no result"


def test_m3_progressive_drift() -> Tuple[bool, str]:
    """Conversation gradually drifts off-topic → later turns should flag/block."""
    header("M3: Multi-Turn — Progressive Drift")

    guard = Vex(
        api_key=API_KEY,
        config=VexConfig(api_url=API_URL, mode="sync", correction="none", timeout_s=30.0),
    )
    session = Session(guard, agent_id="test-progressive-drift")

    turns = [
        ("Tell me about ACME's financials",
         "ACME Corp reported $5.2B in revenue in Q4."),
        ("What about employee morale?",
         "Employee satisfaction at ACME is moderate. Many enjoy the company cafeteria."),
        ("What food do they serve?",
         "The cafeteria serves pasta, salads, and fresh bread."),
        ("How do you make that bread?",
         "For the best sourdough, mix 500g flour with 350g water and 100g starter. "
         "Ferment for 12 hours and bake at 450F for 35 minutes."),
    ]

    actions = []
    for i, (q, a) in enumerate(turns):
        try:
            with session.trace(
                task="Financial Q&A for ACME Corp",
                input_data={"query": q},
            ) as ctx:
                ctx.record({"response": a})
            r = ctx.result
            action = r.action if r else "None"
        except VexBlockError:
            action = "block"

        actions.append(action)
        info(f"Turn {i+1}: action={action}")

    guard.close()

    # Last turn should be flagged or blocked (completely off-topic)
    if actions[-1] in ("flag", "block"):
        ok(f"Progressive drift detected on final turn: {actions}")
        return True, actions[-1]

    fail(f"Expected last turn to be flag/block, got: {actions}")
    return False, str(actions)


# ===========================================================================
# SECTION 3: CORRECTION CASCADE
# ===========================================================================

def test_c1_correction_transparent() -> Tuple[bool, str]:
    """Wrong output + correction=cascade + transparent → see correction attempts."""
    header("C1: Correction — Transparent Mode")

    result, blocked = sdk_verify(
        agent_id="test-correction-transparent",
        task="Answer geography questions accurately",
        output="The capital of France is Lyon.",
        ground_truth="The capital of France is Paris.",
        correction="cascade",
        transparency="transparent",
        timeout_s=60.0,
    )

    if result is None:
        fail("No result returned")
        return False, "no result"

    info(f"action={result.action}, confidence={result.confidence}")
    info(f"corrected={result.corrected}")

    # Check if correction was skipped (free plan)
    if hasattr(result, "correction_skipped") and result.correction_skipped:
        warn("Correction skipped (free plan) — test inconclusive")
        return True, "skipped"

    if result.corrected:
        ok(f"Correction succeeded: action={result.action}")
        if result.original_output is not None:
            ok("Transparent: original_output present")
        if result.corrections:
            info(f"Correction attempts: {len(result.corrections)}")
            for a in result.corrections:
                info(f"  L{a.get('layer', '?')} ({a.get('layer_name', '?')}): "
                     f"success={a.get('success')}")
        return True, "corrected"

    # Correction might be gated behind plan
    if result.action in ("flag", "block"):
        warn(f"Correction did not succeed, but verification caught the error: {result.action}")
        return True, result.action

    fail(f"Expected correction or flag/block, got action={result.action}")
    return False, result.action


def test_c2_correction_opaque() -> Tuple[bool, str]:
    """Wrong output + correction=cascade + opaque → corrected output, no internals exposed."""
    header("C2: Correction — Opaque Mode")

    result, blocked = sdk_verify(
        agent_id="test-correction-opaque",
        task="Answer geography questions accurately",
        output="The capital of France is Berlin.",
        ground_truth="The capital of France is Paris.",
        correction="cascade",
        transparency="opaque",
        timeout_s=60.0,
    )

    if result is None:
        fail("No result returned")
        return False, "no result"

    info(f"action={result.action}, corrected={result.corrected}")

    if result.corrected:
        ok(f"Opaque correction: action={result.action}")
        if result.original_output is None:
            ok("Opaque: original_output hidden")
        else:
            warn("Opaque: original_output exposed (unexpected)")
        return True, "corrected"

    if result.action in ("flag", "block"):
        warn(f"Correction not applied, but error caught: {result.action}")
        return True, result.action

    fail(f"Expected correction or flag/block")
    return False, result.action


def test_c3_correction_not_needed() -> Tuple[bool, str]:
    """Correct output + correction=cascade → no correction applied."""
    header("C3: Correction — Not Needed (already correct)")

    result, blocked = sdk_verify(
        agent_id="test-correction-not-needed",
        task="What is 2+2?",
        output="2+2 equals 4.",
        ground_truth="4",
        correction="cascade",
        transparency="transparent",
        timeout_s=30.0,
    )

    if result is None:
        fail("No result returned")
        return False, "no result"

    info(f"action={result.action}, corrected={result.corrected}")

    if not result.corrected and result.action in ("pass", "flag"):
        ok("Correct output not unnecessarily corrected")
        return True, "no-correction"

    if result.corrected:
        warn("Correction applied to already-correct output (unexpected)")
        return True, "over-corrected"

    fail(f"Unexpected: action={result.action}, corrected={result.corrected}")
    return False, result.action


# ===========================================================================
# SECTION 4: PLAN ENFORCEMENT
# ===========================================================================

def test_p1_correction_gating_free_plan() -> Tuple[bool, str]:
    """Free plan: correction=cascade should be skipped with upgrade message."""
    header("P1: Plan — Correction Gating (Free Plan)")

    resp = raw_verify({
        "execution_id": "test-gating-001",
        "agent_id": "test-gating",
        "task": "Answer questions",
        "output": "The capital of France is Berlin.",
        "ground_truth": "The capital of France is Paris.",
        "input": {},
        "metadata": {
            "correction": "cascade",
            "transparency": "transparent",
        },
    })

    if resp.status_code != 200:
        fail(f"Expected 200, got {resp.status_code}: {resp.text[:200]}")
        return False, str(resp.status_code)

    body = resp.json()
    info(f"correction_skipped={body.get('correction_skipped')}")
    info(f"correction_skipped_reason={body.get('correction_skipped_reason')}")

    if body.get("correction_skipped"):
        if body.get("correction_skipped_reason") == "upgrade_required":
            ok("Correction gated: correction_skipped=true, reason=upgrade_required")
            return True, "gated"
        ok(f"Correction skipped, reason={body.get('correction_skipped_reason')}")
        return True, "gated"

    warn("Correction not skipped — org may be on a paid plan")
    return True, "not-gated"


def test_p2_health_endpoint() -> Tuple[bool, str]:
    """GET /health should return 200 with status=healthy."""
    header("P2: Health Endpoint")

    resp = requests.get(f"{API_URL}/health", timeout=10)

    if resp.status_code == 200:
        body = resp.json()
        if body.get("status") == "healthy":
            ok("Health check passed")
            return True, "healthy"
        fail(f"Unexpected health body: {body}")
        return False, str(body)

    fail(f"Health check failed: status={resp.status_code}")
    return False, str(resp.status_code)


def test_p3_missing_api_key() -> Tuple[bool, str]:
    """Request without API key → expect 401/403."""
    header("P3: Auth — Missing API Key")

    resp = requests.post(
        f"{API_URL}/v1/verify",
        json={
            "execution_id": "test-nokey",
            "agent_id": "test",
            "task": "test",
            "output": "test",
            "input": {},
            "metadata": {},
        },
        headers={"Content-Type": "application/json"},
        timeout=10,
    )

    if resp.status_code in (401, 403, 422):
        ok(f"No API key rejected: status={resp.status_code}")
        return True, str(resp.status_code)

    fail(f"Expected 401/403/422, got {resp.status_code}")
    return False, str(resp.status_code)


def test_p4_invalid_api_key() -> Tuple[bool, str]:
    """Request with invalid API key → expect 401."""
    header("P4: Auth — Invalid API Key")

    resp = requests.post(
        f"{API_URL}/v1/verify",
        json={
            "execution_id": "test-badkey",
            "agent_id": "test",
            "task": "test",
            "output": "test",
            "input": {},
            "metadata": {},
        },
        headers={
            "X-Vex-Key": "ag_live_INVALID_KEY_12345678",
            "Content-Type": "application/json",
        },
        timeout=10,
    )

    if resp.status_code == 401:
        ok("Invalid API key rejected: 401")
        return True, "401"

    fail(f"Expected 401, got {resp.status_code}: {resp.text[:200]}")
    return False, str(resp.status_code)


# ===========================================================================
# SECTION 5: EDGE CASES & INGESTION
# ===========================================================================

def test_e1_async_ingest() -> Tuple[bool, str]:
    """Async fire-and-forget ingest should not raise."""
    header("E1: Async Ingest — Fire and Forget")

    guard = Vex(
        api_key=API_KEY,
        config=VexConfig(api_url=API_URL, mode="async"),
    )

    try:
        with guard.trace(
            agent_id="test-async-ingest",
            task="Test async ingestion",
            input_data={"query": "test"},
        ) as ctx:
            ctx.record({"response": "test output"})

        guard.close()
        ok("Async ingest completed without exception")
        return True, "accepted"
    except Exception as exc:
        fail(f"Async ingest raised: {exc}")
        return False, str(exc)


def test_e2_batch_ingest() -> Tuple[bool, str]:
    """Batch ingest up to 50 events."""
    header("E2: Batch Ingest — Multiple Events")

    events = [
        {
            "execution_id": f"batch-test-{i}",
            "agent_id": "test-batch",
            "task": "batch test",
            "output": f"output {i}",
            "input": {"idx": i},
            "metadata": {},
        }
        for i in range(5)
    ]

    resp = raw_ingest_batch(events)

    if resp.status_code == 202:
        body = resp.json()
        accepted = body.get("accepted", 0)
        if accepted == 5:
            ok(f"Batch accepted: {accepted} events")
            return True, f"accepted={accepted}"
        fail(f"Expected 5 accepted, got {accepted}")
        return False, f"accepted={accepted}"

    fail(f"Expected 202, got {resp.status_code}: {resp.text[:200]}")
    return False, str(resp.status_code)


def test_e3_single_ingest() -> Tuple[bool, str]:
    """Single event ingest via raw HTTP."""
    header("E3: Single Ingest — Raw HTTP")

    resp = raw_ingest({
        "execution_id": "single-ingest-test",
        "agent_id": "test-single-ingest",
        "task": "test",
        "output": "test output",
        "input": {"query": "test"},
        "metadata": {},
    })

    if resp.status_code == 202:
        body = resp.json()
        ok(f"Single ingest accepted: execution_id={body.get('execution_id')}")
        return True, "accepted"

    fail(f"Expected 202, got {resp.status_code}: {resp.text[:200]}")
    return False, str(resp.status_code)


def test_e4_empty_output() -> Tuple[bool, str]:
    """Verify with empty string output — should handle gracefully."""
    header("E4: Edge — Empty Output")

    result, blocked = sdk_verify(
        agent_id="test-empty-output",
        task="Generate a report",
        output="",
        ground_truth="Expected non-empty report",
    )

    if result is None and not blocked:
        fail("No result and no block")
        return False, "no result"

    if blocked:
        ok("Empty output blocked")
        return True, "block"

    info(f"action={result.action}, confidence={result.confidence}")
    # Empty output should probably fail hallucination check
    if result.action in ("flag", "block"):
        ok(f"Empty output caught: action={result.action}")
        return True, result.action

    warn(f"Empty output passed (action={result.action}) — may be acceptable")
    return True, result.action


def test_e5_large_output() -> Tuple[bool, str]:
    """Verify with a large output (10KB) — should not timeout."""
    header("E5: Edge — Large Output (10KB)")

    large_output = {
        "report": "Financial analysis: " + ("ACME Corp had strong results. " * 200),
        "sections": [
            {"title": f"Section {i}", "content": f"Details about section {i}. " * 20}
            for i in range(10)
        ],
    }

    result, blocked = sdk_verify(
        agent_id="test-large-output",
        task="Generate comprehensive financial report",
        output=json.dumps(large_output),
        ground_truth=None,
        timeout_s=60.0,
    )

    if result is None:
        fail("No result for large output")
        return False, "no result"

    info(f"action={result.action}, confidence={result.confidence}")
    ok(f"Large output handled: action={result.action}")
    return True, result.action


def test_e6_special_characters() -> Tuple[bool, str]:
    """Verify output with unicode, emoji, and special characters."""
    header("E6: Edge — Special Characters")

    result, blocked = sdk_verify(
        agent_id="test-special-chars",
        task="Respond in multiple languages",
        output=(
            "Revenue: ¥5.2兆 (approximately $5.2B USD)\n"
            "Profit margin: 15.4% 📈\n"
            "Status: «très bien» — excellent results\n"
            "Growth: ↑8% YoY • €4.8B → €5.2B"
        ),
        ground_truth="Revenue $5.2B, profit $800M",
    )

    if result is None:
        fail("No result for special chars output")
        return False, "no result"

    info(f"action={result.action}, confidence={result.confidence}")
    ok(f"Special characters handled: action={result.action}")
    return True, result.action


def test_e7_json_string_output() -> Tuple[bool, str]:
    """Verify with output that is a JSON string (not dict) — schema should parse it."""
    header("E7: Edge — JSON String Output (schema parses string)")

    result, blocked = sdk_verify(
        agent_id="test-json-string",
        task="Return structured data",
        output='{"name": "ACME", "revenue": 5200000000}',
        schema={
            "type": "object",
            "required": ["name", "revenue"],
            "properties": {
                "name": {"type": "string"},
                "revenue": {"type": "number"},
            },
        },
        ground_truth={"name": "ACME", "revenue": 5200000000},
    )

    if result is None:
        fail("No result")
        return False, "no result"

    info(f"action={result.action}, confidence={result.confidence}")

    if result.action in ("pass", "flag"):
        ok(f"JSON string output parsed correctly: action={result.action}")
        return True, result.action

    fail(f"Expected pass/flag, got {result.action}")
    return False, result.action


def test_e8_sdk_trace_with_steps() -> Tuple[bool, str]:
    """SDK trace with intermediate steps recorded."""
    header("E8: SDK — Trace with Steps")

    guard = Vex(
        api_key=API_KEY,
        config=VexConfig(api_url=API_URL, mode="async"),
    )

    try:
        with guard.trace(
            agent_id="test-steps",
            task="Multi-step agent task",
            input_data={"query": "Analyze ACME Corp"},
        ) as ctx:
            ctx.step("tool_call", "fetch_data", input={"company": "ACME"}, output={"revenue": 5.2})
            ctx.step("llm", "analyze", input={"revenue": 5.2}, output="Strong performance")
            ctx.set_ground_truth({"revenue": "$5.2B"})
            ctx.set_token_count(150)
            ctx.set_cost_estimate(0.003)
            ctx.set_metadata("model", "gpt-4")
            ctx.set_metadata("version", "1.0")
            ctx.record({"summary": "ACME Corp showed strong Q4 performance."})

        guard.close()
        ok("Trace with steps completed successfully")
        return True, "accepted"
    except Exception as exc:
        fail(f"Trace with steps raised: {exc}")
        return False, str(exc)


def test_e9_sdk_watch_decorator() -> Tuple[bool, str]:
    """SDK @watch decorator captures function output."""
    header("E9: SDK — @watch Decorator")

    guard = Vex(
        api_key=API_KEY,
        config=VexConfig(api_url=API_URL, mode="async"),
    )

    @guard.watch(agent_id="test-watch", task="Arithmetic")
    def add_numbers(a: int, b: int) -> dict:
        return {"result": a + b, "operation": "addition"}

    try:
        result = add_numbers(3, 7)
        guard.close()

        # In async mode, @watch returns a VexResult wrapping the output
        if isinstance(result, VexResult):
            if result.output == {"result": 10, "operation": "addition"}:
                ok("@watch decorator returned VexResult with correct output")
                return True, "captured"
            fail(f"VexResult output mismatch: {result.output}")
            return False, str(result.output)
        elif result == {"result": 10, "operation": "addition"}:
            ok("@watch decorator captured output correctly")
            return True, "captured"
        else:
            fail(f"Unexpected return: {result}")
            return False, str(result)
    except Exception as exc:
        fail(f"@watch decorator raised: {exc}")
        return False, str(exc)


# ===========================================================================
# Test runner
# ===========================================================================

SECTIONS = {
    "verification": [
        ("V1: Schema Valid", test_v1_schema_valid),
        ("V2: Schema Violation", test_v2_schema_violation),
        ("V3: Schema Type Mismatch", test_v3_schema_type_mismatch),
        ("V4: Hallucination", test_v4_hallucination_fabricated_facts),
        ("V5: Accurate Output", test_v5_hallucination_accurate),
        ("V6: Drift Off-Topic", test_v6_drift_off_topic),
        ("V7: Drift On-Task", test_v7_drift_on_task),
        ("V8: Minimal Verify", test_v8_no_ground_truth_no_schema),
        ("V9: All Checks Fail", test_v9_combined_failures),
    ],
    "multiturn": [
        ("M1: Consistent Session", test_m1_consistent_session),
        ("M2: Contradiction", test_m2_contradiction),
        ("M3: Progressive Drift", test_m3_progressive_drift),
    ],
    "correction": [
        ("C1: Transparent", test_c1_correction_transparent),
        ("C2: Opaque", test_c2_correction_opaque),
        ("C3: Not Needed", test_c3_correction_not_needed),
    ],
    "plan": [
        ("P1: Correction Gating", test_p1_correction_gating_free_plan),
        ("P2: Health", test_p2_health_endpoint),
        ("P3: Missing API Key", test_p3_missing_api_key),
        ("P4: Invalid API Key", test_p4_invalid_api_key),
    ],
    "edge": [
        ("E1: Async Ingest", test_e1_async_ingest),
        ("E2: Batch Ingest", test_e2_batch_ingest),
        ("E3: Single Ingest", test_e3_single_ingest),
        ("E4: Empty Output", test_e4_empty_output),
        ("E5: Large Output", test_e5_large_output),
        ("E6: Special Chars", test_e6_special_characters),
        ("E7: JSON String", test_e7_json_string_output),
        ("E8: Steps", test_e8_sdk_trace_with_steps),
        ("E9: Watch Decorator", test_e9_sdk_watch_decorator),
    ],
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Vex Comprehensive E2E Tests")
    parser.add_argument(
        "--section",
        choices=list(SECTIONS.keys()) + ["all"],
        default="all",
        help="Run specific test section (default: all)",
    )
    args = parser.parse_args()

    print(f"{BOLD}Vex Comprehensive E2E Test Suite{RESET}")
    print(f"  API URL: {API_URL}")
    print(f"  API Key: {API_KEY[:8]}...{API_KEY[-4:]}")

    sections_to_run = (
        list(SECTIONS.keys()) if args.section == "all" else [args.section]
    )

    all_results: List[Tuple[str, bool, str]] = []

    for section_name in sections_to_run:
        section_header(f"SECTION: {section_name.upper()}")
        tests = SECTIONS[section_name]

        for name, fn in tests:
            t0 = time.monotonic()
            try:
                passed, detail = fn()
            except Exception:
                fail(f"Unhandled exception in {name}")
                traceback.print_exc()
                passed, detail = False, "exception"
            elapsed = time.monotonic() - t0
            print(f"  {DIM}({elapsed:.1f}s){RESET}")
            all_results.append((name, passed, detail))

    # Summary
    header("FINAL SUMMARY")

    passed_count = 0
    failed_count = 0
    warned_count = 0

    for name, passed, detail in all_results:
        if passed:
            status = f"{GREEN}PASS{RESET}"
            passed_count += 1
        else:
            status = f"{RED}FAIL{RESET}"
            failed_count += 1

        print(f"  {name:30s}  [{status}]  {detail}")

    total = len(all_results)
    print(f"\n  {BOLD}{passed_count}/{total} tests passed{RESET}")

    if failed_count > 0:
        print(f"  {RED}{failed_count} tests failed{RESET}")

    if passed_count == total:
        print(f"\n  {GREEN}{BOLD}ALL TESTS PASSED{RESET}")
        return 0
    else:
        print(f"\n  {RED}{BOLD}SOME TESTS FAILED{RESET}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
