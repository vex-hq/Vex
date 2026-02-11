#!/usr/bin/env python3
"""Live verification engine test — exercises the full pipeline with real LLM calls.

Runs 10 scenarios through the verification pipeline:
  1. Good output      — passes schema, no hallucination, on-task      → expect PASS
  2. Hallucinated     — fabricated facts not in ground truth           → expect BLOCK
  3. Drifted          — output completely off-topic                    → expect FLAG/BLOCK
  4. Schema violation — output missing required fields                 → expect BLOCK
  5. Multi-turn consistent — 3-turn financial Q&A, all consistent     → expect PASS
  6. Progressive drift — 4 turns gradually going off-topic            → expect FLAG/BLOCK
  7. Self-contradiction — agent contradicts itself across turns        → expect FLAG/BLOCK
  8. Correction: schema fix — typo in key corrected by L1 Repair      → expect PASS (corrected)
  9. Correction: hallucination — fabricated numbers fixed by L2 Regen  → expect PASS/FLAG (corrected)
 10. Correction: off-topic — pizza recipe corrected to financial data  → expect PASS/FLAG (corrected)

Usage:
    export LITELLM_API_URL=https://litellm.oppla.dev/v1
    export LITELLM_API_KEY=sk-litellm-...
    export VERIFICATION_MODEL=openai/gpt-5.2
    export VERIFICATION_TIMEOUT_S=30

    python3 scripts/test_live_verification.py
"""

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Add service paths
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "services" / "verification-engine"))
sys.path.insert(0, str(ROOT / "services" / "shared"))

from engine.correction import correct as run_correction, select_layer
from engine.models import (
    ConversationTurn,
    CorrectionAttempt,
    VerificationConfig,
    VerificationResult,
)
from engine.pipeline import verify

MAX_CORRECTION_ATTEMPTS = 2
CORRECTION_TIMEOUT_S = 30.0

# Colored output helpers
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

ACTION_COLORS = {"pass": GREEN, "flag": YELLOW, "block": RED}


def print_header(title: str):
    print(f"\n{'='*70}")
    print(f"{BOLD}{CYAN}{title}{RESET}")
    print(f"{'='*70}")


def print_result(
    result: VerificationResult,
    expected_actions: List[str],
    corrected: bool = False,
    expect_corrected: Optional[bool] = None,
    correction_attempts: Optional[List[CorrectionAttempt]] = None,
) -> bool:
    color = ACTION_COLORS.get(result.action, "")
    actual = result.action.upper()
    expected_str = "/".join(a.upper() for a in expected_actions)

    action_match = result.action in expected_actions
    correction_match = (
        expect_corrected is None or corrected == expect_corrected
    )
    match = action_match and correction_match

    status = f"{GREEN}CORRECT{RESET}" if match else f"{RED}UNEXPECTED{RESET}"

    print(f"\n  {BOLD}Confidence:{RESET}  {result.confidence:.3f}" if result.confidence else f"\n  {BOLD}Confidence:{RESET}  None")
    print(f"  {BOLD}Action:{RESET}      {color}{actual}{RESET}  (expected: {expected_str})  [{status}]")
    print(f"\n  {BOLD}Per-check results:{RESET}")
    for name, check in result.checks.items():
        score_str = f"{check.score:.2f}" if check.score is not None else "None"
        passed_str = f"{GREEN}PASS{RESET}" if check.passed else f"{RED}FAIL{RESET}"
        print(f"    {name:15s}  score={score_str:>5s}  {passed_str}")
        if check.details and not check.details.get("skipped"):
            for k, v in check.details.items():
                if isinstance(v, list) and v:
                    print(f"      {k}: {v}")
                elif isinstance(v, str) and v:
                    print(f"      {k}: {v}")

    # Correction details
    if expect_corrected is not None:
        corrected_status = (
            f"{GREEN}YES{RESET}" if corrected else f"{YELLOW}NO{RESET}"
        )
        expected_c = "YES" if expect_corrected else "NO"
        c_match = (
            f"{GREEN}CORRECT{RESET}"
            if corrected == expect_corrected
            else f"{RED}UNEXPECTED{RESET}"
        )
        print(f"\n  {BOLD}Corrected:{RESET}   {corrected_status}  (expected: {expected_c})  [{c_match}]")

    if correction_attempts:
        print(f"  {BOLD}Correction attempts:{RESET}")
        for attempt in correction_attempts:
            success_str = (
                f"{GREEN}SUCCESS{RESET}" if attempt.success else f"{RED}FAILED{RESET}"
            )
            print(
                f"    L{attempt.layer} ({attempt.layer_name:20s})  "
                f"{attempt.latency_ms:7.0f}ms  {success_str}"
            )

    return match


async def verify_with_correction(
    output: Any,
    task: Optional[str] = None,
    schema: Optional[Dict[str, Any]] = None,
    ground_truth: Any = None,
    conversation_history: Optional[List[ConversationTurn]] = None,
    config: Optional[VerificationConfig] = None,
) -> Tuple[VerificationResult, bool, Any, List[CorrectionAttempt]]:
    """Run verify, then attempt correction cascade if the output fails.

    1. Runs initial ``verify()`` on the output.
    2. If the action is not "pass", picks a starting layer via ``select_layer``.
    3. Loops up to ``MAX_CORRECTION_ATTEMPTS`` times:
       - Calls ``run_correction()`` at the current layer.
       - If the correction produces output, re-verifies it.
       - If the re-verification passes, breaks.
       - Otherwise escalates to the next layer.
    4. Returns the final result, whether correction succeeded, the final
       output, and a list of all correction attempts.

    Returns:
        Tuple of (final_result, corrected, final_output, correction_attempts).
    """
    result = await verify(
        output=output,
        task=task,
        schema=schema,
        ground_truth=ground_truth,
        conversation_history=conversation_history,
        config=config,
    )

    if result.action == "pass":
        return result, False, output, []

    # Correction cascade
    layer = select_layer(result)
    attempts: List[CorrectionAttempt] = []
    current_output = output
    current_result = result

    for _ in range(MAX_CORRECTION_ATTEMPTS):
        if layer > 3:
            break

        attempt = await run_correction(
            layer=layer,
            output=current_output,
            task=task,
            checks=current_result.checks,
            schema=schema,
            ground_truth=ground_truth,
            conversation_history=conversation_history,
        )

        # Fill in context from the triggering verification
        attempt.input_action = current_result.action
        attempt.input_confidence = current_result.confidence

        if attempt.corrected_output is None:
            attempt.success = False
            attempts.append(attempt)
            layer += 1
            continue

        # Re-verify the corrected output
        re_result = await verify(
            output=attempt.corrected_output,
            task=task,
            schema=schema,
            ground_truth=ground_truth,
            conversation_history=conversation_history,
            config=config,
        )

        attempt.verification = re_result.dict()
        attempt.success = re_result.action == "pass"
        attempts.append(attempt)

        if re_result.action == "pass":
            return re_result, True, attempt.corrected_output, attempts

        # Escalate
        current_output = attempt.corrected_output
        current_result = re_result
        layer += 1

    # All attempts exhausted — return the last verification result
    return current_result, False, current_output, attempts


async def main():
    logging.basicConfig(level=logging.WARNING)

    model = os.environ.get("VERIFICATION_MODEL", "claude-haiku-4-5-20251001")
    api_base = os.environ.get("LITELLM_API_URL", "not set")
    print(f"{BOLD}AgentGuard Live Verification Test{RESET}")
    print(f"  Model:    {model}")
    print(f"  API Base: {api_base}")
    print(f"  Timeout:  {os.environ.get('VERIFICATION_TIMEOUT_S', '5')}s")

    config = VerificationConfig(
        pass_threshold=0.8,
        flag_threshold=0.5,
    )

    results = []

    # ---------------------------------------------------------------
    # Scenario 1: Good output — everything checks out
    # ---------------------------------------------------------------
    print_header("Scenario 1: GOOD OUTPUT (expect PASS)")
    print("  Task: Generate a financial summary for ACME Corp")
    print("  Output has correct revenue, profit, and employee count")

    r1 = await verify(
        output={
            "company": "ACME Corp",
            "revenue": "$5.2 billion",
            "profit": "$800 million",
            "employees": 12000,
            "summary": "ACME Corp reported strong Q4 results with revenue of $5.2B."
        },
        task="Generate a financial summary for ACME Corp based on Q4 data",
        schema={
            "type": "object",
            "required": ["company", "revenue", "profit"],
            "properties": {
                "company": {"type": "string"},
                "revenue": {"type": "string"},
                "profit": {"type": "string"},
                "employees": {"type": "integer"},
                "summary": {"type": "string"},
            }
        },
        ground_truth={
            "company": "ACME Corp",
            "revenue": "$5.2 billion",
            "profit": "$800 million",
            "employees": 12000,
        },
        config=config,
    )
    results.append(("Good Output", print_result(r1, ["pass"])))

    # ---------------------------------------------------------------
    # Scenario 2: Hallucinated output — fabricated facts
    # ---------------------------------------------------------------
    print_header("Scenario 2: HALLUCINATED OUTPUT (expect BLOCK)")
    print("  Task: Summarize ACME Corp financials")
    print("  Output fabricates an acquisition and inflates revenue")

    r2 = await verify(
        output={
            "company": "ACME Corp",
            "revenue": "$15 billion",
            "profit": "$3 billion",
            "employees": 50000,
            "summary": "ACME Corp acquired GlobalTech for $2B and reported record revenue of $15B. The company also announced plans to IPO on NASDAQ."
        },
        task="Summarize ACME Corp financials based on Q4 data",
        schema={
            "type": "object",
            "required": ["company", "revenue", "profit"],
            "properties": {
                "company": {"type": "string"},
                "revenue": {"type": "string"},
                "profit": {"type": "string"},
            }
        },
        ground_truth={
            "company": "ACME Corp",
            "revenue": "$5.2 billion",
            "profit": "$800 million",
            "employees": 12000,
            "publicly_traded": False,
            "acquisitions": [],
        },
        config=config,
    )
    results.append(("Hallucinated", print_result(r2, ["block", "flag"])))

    # ---------------------------------------------------------------
    # Scenario 3: Drifted output — completely off-topic
    # ---------------------------------------------------------------
    print_header("Scenario 3: DRIFTED OUTPUT (expect FLAG/BLOCK)")
    print("  Task: Generate a financial summary")
    print("  Output is a recipe for chocolate cake instead")

    r3 = await verify(
        output="To make a chocolate cake, preheat your oven to 350F. Mix 2 cups flour, 1 cup sugar, 3/4 cup cocoa powder. Add 2 eggs, 1 cup milk, and 1/2 cup vegetable oil. Bake for 30 minutes.",
        task="Generate a financial summary for ACME Corp based on Q4 data",
        ground_truth=None,  # no ground truth to check against
        schema=None,  # no schema requirement
        config=config,
    )
    results.append(("Drifted", print_result(r3, ["block", "flag"])))

    # ---------------------------------------------------------------
    # Scenario 4: Schema violation — missing required fields
    # ---------------------------------------------------------------
    print_header("Scenario 4: SCHEMA VIOLATION (expect BLOCK)")
    print("  Task: Return structured customer data")
    print("  Output is missing required 'email' and 'id' fields")

    r4 = await verify(
        output={
            "name": "John Doe",
            "phone": "555-1234",
        },
        task="Return structured customer data with all required fields",
        schema={
            "type": "object",
            "required": ["id", "name", "email"],
            "properties": {
                "id": {"type": "integer"},
                "name": {"type": "string"},
                "email": {"type": "string", "format": "email"},
            }
        },
        ground_truth={
            "id": 42,
            "name": "John Doe",
            "email": "john@example.com",
        },
        config=config,
    )
    results.append(("Schema Violation", print_result(r4, ["block"])))

    # ---------------------------------------------------------------
    # Scenario 5: Multi-turn consistent — conversation stays coherent
    # ---------------------------------------------------------------
    print_header("Scenario 5: MULTI-TURN CONSISTENT (expect PASS)")
    print("  Task: Financial Q&A for ACME Corp")
    print("  3-turn conversation, all consistent and on-topic")

    history_5 = [
        ConversationTurn(
            sequence_number=0,
            input="What is ACME Corp's revenue?",
            output="ACME Corp's Q4 revenue was $5.2 billion.",
            task="Financial Q&A for ACME Corp",
        ),
        ConversationTurn(
            sequence_number=1,
            input="And what about their profit?",
            output="ACME Corp reported a profit of $800 million in Q4.",
            task="Financial Q&A for ACME Corp",
        ),
    ]

    r5 = await verify(
        output="With revenue of $5.2B and profit of $800M, ACME Corp's profit margin was approximately 15.4% in Q4.",
        task="Financial Q&A for ACME Corp",
        ground_truth={
            "company": "ACME Corp",
            "revenue": "$5.2 billion",
            "profit": "$800 million",
            "employees": 12000,
        },
        conversation_history=history_5,
        config=config,
    )
    results.append(("Multi-turn Consistent", print_result(r5, ["pass"])))

    # ---------------------------------------------------------------
    # Scenario 6: Progressive drift — conversation wanders off-topic
    # ---------------------------------------------------------------
    print_header("Scenario 6: PROGRESSIVE DRIFT (expect FLAG/BLOCK)")
    print("  Task: Financial Q&A for ACME Corp")
    print("  Agent starts on-topic then gradually drifts to cooking")

    history_6 = [
        ConversationTurn(
            sequence_number=0,
            input="Tell me about ACME Corp's financials",
            output="ACME Corp reported $5.2B in revenue in Q4.",
            task="Financial Q&A for ACME Corp",
        ),
        ConversationTurn(
            sequence_number=1,
            input="What about employee satisfaction?",
            output="Employee satisfaction at ACME is moderate. Many enjoy the company cafeteria.",
            task="Financial Q&A for ACME Corp",
        ),
        ConversationTurn(
            sequence_number=2,
            input="What's served in the cafeteria?",
            output="The cafeteria serves various dishes including pasta, salads, and freshly baked bread.",
            task="Financial Q&A for ACME Corp",
        ),
    ]

    r6 = await verify(
        output="For the best bread, you need to use sourdough starter. Mix 500g flour with 350g water and 100g starter. Let it ferment for 12 hours. Preheat oven to 450F and bake for 35 minutes.",
        task="Financial Q&A for ACME Corp",
        ground_truth=None,
        conversation_history=history_6,
        config=config,
    )
    results.append(("Progressive Drift", print_result(r6, ["block", "flag"])))

    # ---------------------------------------------------------------
    # Scenario 7: Self-contradiction — agent contradicts prior turn
    # ---------------------------------------------------------------
    print_header("Scenario 7: SELF-CONTRADICTION (expect FLAG/BLOCK)")
    print("  Task: Financial Q&A for ACME Corp")
    print("  Agent says revenue is $5.2B in turn 0, then claims $15B in turn 2")

    history_7 = [
        ConversationTurn(
            sequence_number=0,
            input="What is ACME Corp's revenue?",
            output="ACME Corp's Q4 revenue was $5.2 billion.",
            task="Financial Q&A for ACME Corp",
        ),
        ConversationTurn(
            sequence_number=1,
            input="How does that compare to last year?",
            output="Revenue grew 8% year-over-year from $4.8 billion.",
            task="Financial Q&A for ACME Corp",
        ),
    ]

    r7 = await verify(
        output="ACME Corp's Q4 revenue was $15 billion, making it one of the largest companies in the sector. The company has been growing rapidly with 200% year-over-year growth.",
        task="Financial Q&A for ACME Corp",
        ground_truth={
            "company": "ACME Corp",
            "revenue": "$5.2 billion",
            "yoy_growth": "8%",
        },
        conversation_history=history_7,
        config=config,
    )
    results.append(("Self-contradiction", print_result(r7, ["block", "flag"])))

    # ---------------------------------------------------------------
    # Scenario 8: Schema violation corrected — L1 Repair fixes typo
    # ---------------------------------------------------------------
    print_header("Scenario 8: SCHEMA CORRECTION — L1 REPAIR (expect PASS, corrected)")
    print("  Task: Generate financial summary")
    print('  Output has "revnue" typo → L1 Repair should fix to "revenue"')

    r8, corrected_8, final_8, attempts_8 = await verify_with_correction(
        output={"revnue": 5200000, "profit": 800000},
        task="Generate financial summary",
        schema={
            "type": "object",
            "required": ["revenue", "profit"],
            "properties": {
                "revenue": {"type": "number"},
                "profit": {"type": "number"},
            },
        },
        ground_truth={"revenue": 5200000, "profit": 800000},
        config=config,
    )
    results.append((
        "Schema Correction (L1)",
        print_result(
            r8, ["pass"],
            corrected=corrected_8,
            expect_corrected=True,
            correction_attempts=attempts_8,
        ),
    ))

    # ---------------------------------------------------------------
    # Scenario 9: Hallucination corrected — L2 Constrained Regen
    # ---------------------------------------------------------------
    print_header("Scenario 9: HALLUCINATION CORRECTION — L2 REGEN (expect PASS/FLAG, corrected)")
    print("  Task: Summarize Q3 earnings")
    print("  Output fabricates $999 trillion revenue → L2 regen should produce factual output")

    r9, corrected_9, final_9, attempts_9 = await verify_with_correction(
        output="Revenue was $999 trillion in Q3, a record-breaking quarter.",
        task="Summarize Q3 earnings",
        ground_truth={"revenue": "$5.2B", "quarter": "Q3 2025"},
        config=config,
    )
    results.append((
        "Hallucination Correction (L2)",
        print_result(
            r9, ["pass", "flag"],
            corrected=corrected_9,
            expect_corrected=True,
            correction_attempts=attempts_9,
        ),
    ))

    # ---------------------------------------------------------------
    # Scenario 10: Off-topic output corrected — cascade recovers
    # ---------------------------------------------------------------
    print_header("Scenario 10: OFF-TOPIC CORRECTION — CASCADE (expect PASS/FLAG, corrected)")
    print("  Task: Provide Q3 financial analysis with revenue and profit figures")
    print("  Output is a pizza recipe → cascade should recover to financial data")

    r10, corrected_10, final_10, attempts_10 = await verify_with_correction(
        output="Let me tell you about my favorite pizza recipe instead of answering your question.",
        task="Provide Q3 financial analysis with revenue and profit figures",
        schema={
            "type": "object",
            "required": ["revenue", "profit", "analysis"],
            "properties": {
                "revenue": {"type": "string"},
                "profit": {"type": "string"},
                "analysis": {"type": "string"},
            },
        },
        ground_truth={"revenue": "$5.2B", "profit": "$800M"},
        config=config,
    )
    results.append((
        "Off-topic Correction",
        print_result(
            r10, ["pass", "flag"],
            corrected=corrected_10,
            expect_corrected=True,
            correction_attempts=attempts_10,
        ),
    ))

    # ---------------------------------------------------------------
    # Summary
    # ---------------------------------------------------------------
    print_header("SUMMARY")
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    for name, ok in results:
        status = f"{GREEN}CORRECT{RESET}" if ok else f"{RED}UNEXPECTED{RESET}"
        print(f"  {name:30s}  [{status}]")

    print(f"\n  {BOLD}{passed}/{total} scenarios produced expected actions{RESET}")

    if passed == total:
        print(f"\n  {GREEN}{BOLD}ALL SCENARIOS PASSED{RESET}")
    else:
        print(f"\n  {YELLOW}{BOLD}Some scenarios had unexpected results — review above{RESET}")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
