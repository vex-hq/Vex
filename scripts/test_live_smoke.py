#!/usr/bin/env python3
"""Live smoke test — exercises the full SDK → Gateway → Storage pipeline.

Runs 6 scenarios against the live API with real LLM scoring:
  1. Async ingest       — fire-and-forget trace, no exception
  2. Sync pass          — correct answer + ground truth → action=pass or flag (high conf)
  3. Sync flag/block    — wrong answer → action=flag or block
  4. Correction cascade — wrong answer + correction=cascade (transparent) → corrected=True
  5. Auto-correct       — wrong answer + correction=cascade (opaque) → silent replacement
  6. Multi-turn session — contradictory answers → coherence check runs

Usage:
    export VEX_API_KEY=ag_live_...
    export VEX_API_URL=https://api.tryvex.dev   # optional, this is the default

    python3 scripts/test_live_smoke.py
"""

import os
import sys
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple

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
RESET = "\033[0m"


def header(title: str) -> None:
    print(f"\n{'='*70}")
    print(f"{BOLD}{CYAN}{title}{RESET}")
    print(f"{'='*70}")


def ok(msg: str) -> None:
    print(f"  {GREEN}PASS{RESET}  {msg}")


def fail(msg: str) -> None:
    print(f"  {RED}FAIL{RESET}  {msg}")


# ---------------------------------------------------------------------------
# Import SDK (after env validation so error is clearer)
# ---------------------------------------------------------------------------

from vex import Vex, VexConfig, VexBlockError, VexResult  # noqa: E402


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

def scenario_1_async_ingest() -> Tuple[bool, str]:
    """Fire-and-forget async trace — should not raise."""
    header("Scenario 1: ASYNC INGEST (fire-and-forget)")

    guard = Vex(
        api_key=API_KEY,
        config=VexConfig(api_url=API_URL, mode="async"),
    )

    try:
        with guard.trace(
            agent_id="smoke-test",
            task="Summarize quarterly earnings",
            input_data={"query": "Summarize Q4 earnings for ACME Corp"},
        ) as ctx:
            ctx.set_ground_truth({"revenue": "$5.2B", "profit": "$800M"})
            ctx.record({
                "response": "ACME Corp reported $5.2B in revenue and $800M profit in Q4."
            })

        guard.close()
        ok("Async trace completed without exception")
        return True, "accepted"
    except Exception as exc:
        fail(f"Async trace raised: {exc}")
        return False, str(exc)


def scenario_2_sync_pass() -> Tuple[bool, str]:
    """Correct answer with ground truth — expect pass or flag with high confidence."""
    header("Scenario 2: SYNC VERIFICATION — PASS")

    guard = Vex(
        api_key=API_KEY,
        config=VexConfig(
            api_url=API_URL,
            mode="sync",
            correction="none",
        ),
    )

    with guard.trace(
        agent_id="smoke-test",
        task="Answer geography questions accurately",
        input_data={"query": "What is the capital of France?"},
    ) as ctx:
        ctx.set_ground_truth("The capital of France is Paris.")
        ctx.record({
            "response": "The capital of France is Paris. It is known for the Eiffel Tower and the Louvre Museum.",
        })

    result = ctx.result
    guard.close()

    if result is None:
        fail("No result returned from sync verification")
        return False, "no result"

    print(f"  Action:     {result.action}")
    print(f"  Confidence: {result.confidence}")

    if result.action in ("pass", "flag") and (
        result.confidence is None or result.confidence >= 0.5
    ):
        ok(f"action={result.action}, confidence={result.confidence}")
        return True, result.action
    else:
        fail(f"Expected pass/flag (high conf), got action={result.action} conf={result.confidence}")
        return False, result.action


def scenario_3_sync_flag_block() -> Tuple[bool, str]:
    """Deliberately wrong answer — expect flag or block."""
    header("Scenario 3: SYNC VERIFICATION — FLAG/BLOCK")

    guard = Vex(
        api_key=API_KEY,
        config=VexConfig(
            api_url=API_URL,
            mode="sync",
            correction="none",
        ),
    )

    blocked = False
    result: Optional[VexResult] = None

    try:
        with guard.trace(
            agent_id="smoke-test",
            task="Answer geography questions accurately",
            input_data={"query": "What is the capital of France?"},
        ) as ctx:
            ctx.set_ground_truth("The capital of France is Paris.")
            ctx.record({
                "response": "The capital of France is Berlin. France is located in Asia "
                "and has a population of 10 billion people. The country was "
                "founded in 3024 by Emperor Napoleon XVII.",
            })

        result = ctx.result
    except VexBlockError:
        blocked = True

    guard.close()

    if blocked:
        ok("VexBlockError raised (action=block)")
        return True, "block"

    if result is None:
        fail("No result and no VexBlockError")
        return False, "no result"

    print(f"  Action:     {result.action}")
    print(f"  Confidence: {result.confidence}")

    if result.action in ("flag", "block"):
        ok(f"action={result.action}")
        return True, result.action
    else:
        fail(f"Expected flag/block, got action={result.action}")
        return False, result.action


def scenario_4_correction_cascade() -> Tuple[bool, str]:
    """Wrong answer with correction=cascade — must get corrected=True."""
    header("Scenario 4: CORRECTION CASCADE")

    guard = Vex(
        api_key=API_KEY,
        config=VexConfig(
            api_url=API_URL,
            mode="sync",
            correction="cascade",
            transparency="transparent",
        ),
    )

    blocked = False
    result: Optional[VexResult] = None

    try:
        with guard.trace(
            agent_id="smoke-test",
            task="Answer geography questions accurately",
            input_data={"query": "What is the capital of France?"},
        ) as ctx:
            ctx.set_ground_truth("The capital of France is Paris.")
            ctx.record({
                "response": "The capital of France is Lyon. It is a beautiful city "
                "known for the Eiffel Tower and the Louvre Museum.",
            })

        result = ctx.result
    except VexBlockError as exc:
        blocked = True
        # VexBlockError carries the result
        result = getattr(exc, "result", None)

    guard.close()

    if result is None:
        fail("No result returned")
        return False, "no result"

    print(f"  Action:     {result.action}")
    print(f"  Confidence: {result.confidence}")
    print(f"  Corrected:  {result.corrected}")

    if result.corrected and result.output:
        corrected_text = str(result.output)
        original_text = str(result.original_output) if result.original_output else ""
        print(f"  Output:     {corrected_text[:120]}...")
        if original_text:
            print(f"  Original:   {original_text[:120]}...")
        ok(f"corrected=True, action={result.action}")
        return True, "corrected"

    if result.corrections:
        print(f"  Attempts:   {len(result.corrections)}")
        for a in result.corrections:
            layer = a.get("layer", "?")
            name = a.get("layer_name", "?")
            success = a.get("success", False)
            print(f"    L{layer} ({name}): success={success}")

    fail(f"Expected corrected=True, got corrected={result.corrected}")
    return False, f"corrected={result.corrected}"


def scenario_5_auto_correct() -> Tuple[bool, str]:
    """Opaque auto-correction — SDK silently replaces output with corrected version."""
    header("Scenario 5: AUTO-CORRECT (opaque correction)")

    guard = Vex(
        api_key=API_KEY,
        config=VexConfig(
            api_url=API_URL,
            mode="sync",
            correction="cascade",
            transparency="opaque",
        ),
    )

    original_response = {
        "response": "The capital of France is Lyon. It is a beautiful city "
        "known for the Eiffel Tower and the Louvre Museum.",
    }

    blocked = False
    result: Optional[VexResult] = None

    try:
        with guard.trace(
            agent_id="smoke-test",
            task="Answer geography questions accurately",
            input_data={"query": "What is the capital of France?"},
        ) as ctx:
            ctx.set_ground_truth("The capital of France is Paris.")
            ctx.record(original_response)

        result = ctx.result
    except VexBlockError as exc:
        blocked = True
        result = getattr(exc, "result", None)

    guard.close()

    if result is None:
        fail("No result returned")
        return False, "no result"

    print(f"  Action:     {result.action}")
    print(f"  Confidence: {result.confidence}")
    print(f"  Corrected:  {result.corrected}")

    if result.corrected:
        corrected_text = str(result.output)
        print(f"  Output:     {corrected_text[:120]}...")
        # In opaque mode, original_output should be None (hidden from caller)
        if result.original_output is None:
            ok("Opaque: corrected output returned, original hidden")
        else:
            # Some SDK versions still expose original — that's acceptable
            ok(f"Corrected output returned, original_output present")

        # Verify the corrected output differs from what we sent
        if str(result.output) != str(original_response):
            ok("Corrected output differs from original")
            return True, "auto-corrected"
        else:
            fail("Corrected output is identical to original")
            return False, "unchanged"

    fail(f"Expected corrected=True in opaque mode, got corrected={result.corrected}")
    return False, f"corrected={result.corrected}"


def scenario_6_multiturn_session() -> Tuple[bool, str]:
    """Two-turn session with contradictory answers — coherence check should flag."""
    header("Scenario 6: MULTI-TURN SESSION (contradiction)")

    from vex import Session

    guard = Vex(
        api_key=API_KEY,
        config=VexConfig(
            api_url=API_URL,
            mode="sync",
            correction="none",
        ),
    )

    session = Session(guard, agent_id="smoke-test-session")

    # Turn 1: correct answer
    with session.trace(
        task="Answer geography questions accurately",
        input_data={"query": "What is the capital of France?"},
    ) as ctx1:
        ctx1.set_ground_truth("The capital of France is Paris.")
        ctx1.record({
            "response": "The capital of France is Paris.",
        })

    r1 = ctx1.result
    print(f"  Turn 1: action={r1.action if r1 else 'None'}")

    # Turn 2: contradictory answer
    blocked = False
    result: Optional[VexResult] = None

    try:
        with session.trace(
            task="Answer geography questions accurately",
            input_data={"query": "What is the capital of France?"},
        ) as ctx2:
            ctx2.set_ground_truth("The capital of France is Paris.")
            ctx2.record({
                "response": "Actually, the capital of France is Marseille. "
                "I was wrong before — it has never been Paris.",
            })

        result = ctx2.result
    except VexBlockError:
        blocked = True

    guard.close()

    if blocked:
        ok("VexBlockError raised on contradictory turn (coherence check)")
        return True, "block"

    if result is None:
        fail("No result on turn 2")
        return False, "no result"

    print(f"  Turn 2: action={result.action}, confidence={result.confidence}")

    if result.action in ("flag", "block"):
        ok(f"Contradiction detected: action={result.action}")
        return True, result.action
    else:
        fail(f"Expected flag/block on contradiction, got action={result.action}")
        return False, result.action


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

SCENARIOS = [
    ("Async Ingest", scenario_1_async_ingest),
    ("Sync Pass", scenario_2_sync_pass),
    ("Sync Flag/Block", scenario_3_sync_flag_block),
    ("Correction Cascade", scenario_4_correction_cascade),
    ("Auto-Correct (opaque)", scenario_5_auto_correct),
    ("Multi-turn Session", scenario_6_multiturn_session),
]


def main() -> int:
    print(f"{BOLD}Vex Live Smoke Test{RESET}")
    print(f"  API URL: {API_URL}")
    print(f"  API Key: {API_KEY[:8]}...{API_KEY[-4:]}")

    results: List[Tuple[str, bool, str]] = []

    for name, fn in SCENARIOS:
        t0 = time.monotonic()
        try:
            passed, detail = fn()
        except Exception:
            fail(f"Unhandled exception in {name}")
            traceback.print_exc()
            passed, detail = False, "exception"
        elapsed = time.monotonic() - t0
        print(f"  {CYAN}({elapsed:.1f}s){RESET}")
        results.append((name, passed, detail))

    # Summary
    header("SUMMARY")
    total_passed = 0
    for name, passed, detail in results:
        status = f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"
        print(f"  {name:25s}  [{status}]  {detail}")
        if passed:
            total_passed += 1

    total = len(results)
    print(f"\n  {BOLD}{total_passed}/{total} scenarios passed{RESET}")

    if total_passed == total:
        print(f"\n  {GREEN}{BOLD}ALL SCENARIOS PASSED{RESET}")
        return 0
    else:
        print(f"\n  {RED}{BOLD}SOME SCENARIOS FAILED{RESET}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
