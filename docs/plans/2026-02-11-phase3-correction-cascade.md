# Phase 3: Self-Correction Cascade — Design Document

**Date:** February 11, 2026
**Status:** Approved
**Goal:** Graduated self-correction that automatically fixes failed agent outputs before they reach end users.
**Timeline:** Weeks 7-8 (2 weeks)

---

## Overview

Phase 2 shipped active verification — the system judges every agent output and takes action (pass/flag/block). But flag and block are dead ends: the agent developer must manually investigate and fix. Phase 3 adds **automatic correction** — when verification fails, AgentGuard attempts to fix the output through a graduated cascade of increasingly powerful correction strategies, re-verifying each attempt.

This is AgentGuard's key differentiator: no other guardrail tool does server-side output correction with re-verification.

### Key Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Correction location | Server-side (`engine/correction.py`) | Keeps correction logic centralized, works for all SDK consumers, no customer code changes needed. |
| Layer 2 strategy | LLM-as-Proxy Regeneration | Server's LLM generates new output with constraints — does NOT re-run customer's agent. This is the UVP: correction without agent access. |
| Timeout | 10s when correction enabled (up from 2s) | Correction needs 2-3 LLM calls. 10s budget covers initial verify + 2 correction attempts with re-verify. |
| Max attempts | 2 | Diminishing returns beyond 2. Prevents runaway cost. Escalation: L1→L2 or L2→L3. |
| Re-verification | Every corrected output re-verified | Cascade never trusts its own corrections. Full pipeline runs on each corrected output. |
| Correct from original | Always | Layer N+1 gets the original output, not Layer N's failed correction. Prevents error compounding. |
| Activation | `correction="cascade"` in GuardConfig | Opt-in. Default is `"none"` — zero behavior change for existing users. |
| Async mode | No correction | Fire-and-forget stays fire-and-forget. Correction only makes sense in sync mode where caller waits. |

---

## Architecture

```
SDK (sync mode, correction="cascade")
  │
  ├─ POST /v1/verify  (metadata: correction=cascade, transparency=opaque)
  │
  ▼
Sync Gateway (10s timeout)
  │
  ├─ 1. Run verification pipeline
  │     └─ action = pass → return immediately
  │
  ├─ 2. action = flag/block → enter correction cascade
  │     │
  │     ├─ select_layer(verification_result) → starting layer
  │     │
  │     ├─ Attempt 1: correct at Layer N
  │     │   ├─ Re-verify corrected output
  │     │   ├─ pass → return corrected result ✅
  │     │   └─ fail → escalate to Layer N+1
  │     │
  │     ├─ Attempt 2: correct at Layer N+1
  │     │   ├─ Re-verify corrected output
  │     │   ├─ pass → return corrected result ✅
  │     │   └─ fail → block + alert ❌
  │     │
  │     └─ Always uses ORIGINAL output (not failed correction)
  │
  ├─ 3. Emit to Redis (raw + verified + correction metadata)
  │
  ▼
SDK receives GuardResult
  ├─ corrected=True → output is corrected, action="pass"
  ├─ corrected=False, action="flag" → warning logged
  └─ corrected=False, action="block" → AgentGuardBlockError raised
```

---

## Correction Layers

### Layer 1: Repair (Small Model, ~500 tokens)

**When:** Schema violations, formatting errors, minor structural issues.

**How:** Small/fast model (e.g. `gpt-4o-mini`) receives the failed output + specific error details and returns a minimally-edited fix. No regeneration — surgical repair only.

**Prompt:**
```
You are a data repair tool. Fix ONLY the specific errors listed below.
Do NOT change content, meaning, or add information. Make the minimum
edit needed to fix each error.

ORIGINAL OUTPUT:
{output}

ERRORS TO FIX:
{check_failures}

Return ONLY the corrected output. No explanation.
```

**Budget:** ~200-400ms, ~500 tokens

### Layer 2: Constrained Regeneration (Strong Model, Full Regen)

**When:** Hallucination detected, moderate drift, repair insufficient.

**How:** Strong model (e.g. `gpt-4o`) generates a completely new output given the task, input context, and constraints. Does NOT see the failed output — generates fresh to avoid anchoring on wrong content.

This is the UVP: the server regenerates output with full context (task + schema + ground truth + conversation history) without needing to re-run the customer's agent.

**Prompt:**
```
You are a reliable AI assistant. Generate a response for the following task.

TASK: {task}
INPUT CONTEXT: {input}

CONSTRAINTS:
- You MUST follow this schema: {schema}
- Ground truth facts (do NOT contradict): {ground_truth}

CONVERSATION HISTORY:
{formatted_history}

Requirements:
1. Be factually accurate and consistent with ground truth
2. Stay focused on the task
3. Be consistent with prior conversation turns
4. Follow the schema exactly

Generate the response now. Output ONLY the response content.
```

**Budget:** ~800-1500ms, ~2000 tokens

### Layer 3: Full Re-prompt with Failure Feedback (Strong Model)

**When:** Layer 2 failed, severe issues, last resort.

**How:** Strong model receives explicit failure feedback — what went wrong and why — and generates with heightened constraints.

**Prompt:**
```
You are a reliable AI assistant. A previous response to this task
FAILED verification. Generate a corrected response.

TASK: {task}
INPUT CONTEXT: {input}

WHAT WENT WRONG:
{detailed_failure_analysis}

CONSTRAINTS:
- Schema: {schema}
- Ground truth: {ground_truth}
- Conversation history: {formatted_history}

CRITICAL: The previous response failed because of the issues above.
Your response MUST avoid these specific problems. Be conservative
and precise. When uncertain, acknowledge uncertainty rather than
fabricate.

Generate the corrected response now. Output ONLY the response content.
```

**Budget:** ~800-1500ms, ~2500 tokens

### Layer Selection Logic

```python
def select_layer(result: VerificationResult) -> int:
    checks = result.checks

    # Schema-only failure → start at Layer 1 (Repair)
    schema = checks.get("schema")
    non_schema_failed = any(
        not c.passed for name, c in checks.items() if name != "schema"
    )
    if schema and not schema.passed and not non_schema_failed:
        return 1

    # Mild failure (confidence > flag_threshold) → Layer 1
    if result.confidence and result.confidence > 0.5:
        return 1

    # Moderate failure → Layer 2 (Constrained Regen)
    if result.confidence and result.confidence > 0.3:
        return 2

    # Severe failure → Layer 3 (Full Re-prompt)
    return 3
```

---

## Data Models

### Engine Models (`engine/models.py`)

```python
class CorrectionAttempt(BaseModel):
    """Record of a single correction attempt within the cascade."""
    layer: int                          # 1, 2, or 3
    layer_name: str                     # "repair", "constrained_regen", "full_reprompt"
    input_action: str                   # action that triggered correction ("flag" or "block")
    input_confidence: Optional[float]   # confidence before this attempt
    corrected_output: Any               # the output produced by this layer
    verification: Optional[Dict[str, Any]]  # re-verification result
    model_used: str                     # e.g. "gpt-4o-mini", "gpt-4o"
    latency_ms: float                   # time for this correction attempt
    success: bool                       # did re-verification pass?

class CorrectionResult(BaseModel):
    """Full correction cascade outcome."""
    corrected: bool                     # was correction successful?
    final_output: Any                   # the corrected output (or original if failed)
    attempts: List[CorrectionAttempt]   # ordered list of attempts
    total_latency_ms: float             # sum of all attempt latencies
    escalation_path: List[int]          # e.g. [1, 2] — layers attempted
```

### Engine VerificationResult Update

```python
class VerificationResult(BaseModel):
    confidence: Optional[float] = None
    action: str = "pass"
    checks: Dict[str, CheckResult] = Field(default_factory=dict)
    correction: Optional[CorrectionResult] = None  # NEW
```

### Shared Wire Models (`shared/models.py`)

```python
class CorrectionAttemptResponse(BaseModel):
    """Wire format for a single correction attempt."""
    layer: int
    layer_name: str
    corrected_output: Any
    confidence: Optional[float] = None
    action: str
    success: bool
    latency_ms: float

class VerifyResponse(BaseModel):
    execution_id: str
    confidence: Optional[float] = None
    action: str = "pass"
    output: Any
    checks: Dict[str, CheckResult] = Field(default_factory=dict)
    # NEW fields:
    corrected: bool = False
    original_output: Optional[Any] = None
    correction_attempts: Optional[List[CorrectionAttemptResponse]] = None
```

### SDK Models (`sdk/python/agentguard/models.py`)

```python
class GuardResult(BaseModel):
    output: Any
    confidence: Optional[float] = None
    action: str = "pass"
    corrections: Optional[List[Dict[str, Any]]] = None  # EXISTING — now populated
    execution_id: str
    verification: Optional[Dict[str, Any]] = None
    corrected: bool = False             # NEW
    original_output: Optional[Any] = None  # NEW — transparent mode only
```

### Transparency Modes

| Mode | `output` | `original_output` | `correction_attempts` |
|------|----------|-------------------|----------------------|
| `"opaque"` (default) | corrected output | `None` | `None` |
| `"transparent"` | corrected output | original failed output | full attempt list |

**Opaque:** SDK consumer sees corrected output seamlessly — doesn't know correction happened.

**Transparent:** SDK consumer gets full correction history for inspection and custom UIs.

---

## Gateway Orchestration

### Timeout Configuration

```python
CORRECTION_TIMEOUT_S = 10.0   # when correction enabled
DEFAULT_TIMEOUT_S = 2.0       # existing behavior (unchanged)
```

### Endpoint Changes (`services/sync-gateway/app/routes.py`)

```python
@router.post("/v1/verify", response_model=VerifyResponse)
async def verify_endpoint(event: VerifyRequest, request: Request, ...):
    correction_mode = (event.metadata or {}).get("correction", "none")
    transparency = (event.metadata or {}).get("transparency", "opaque")

    timeout = CORRECTION_TIMEOUT_S if correction_mode == "cascade" else DEFAULT_TIMEOUT_S

    try:
        result = await asyncio.wait_for(
            run_verification_with_correction(event, config, correction_mode),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        # Pass-through on timeout — never block the agent
        ...
```

### Correction Orchestration Loop

```python
async def run_verification_with_correction(event, config, correction_mode):
    # Step 1: Initial verification (existing pipeline)
    result = await run_verification(output=event.output, task=event.task, ...)

    if result.action == "pass" or correction_mode != "cascade":
        return result

    # Step 2: Correction cascade
    from engine.correction import correct, select_layer

    attempts = []
    layer = select_layer(result)

    for attempt_num in range(2):  # max 2 attempts
        corrected = await correct(
            layer=layer,
            output=event.output,  # ALWAYS original output
            task=event.task,
            checks=result.checks,
            schema=event.schema_definition,
            ground_truth=event.ground_truth,
            conversation_history=event.conversation_history,
        )

        # Re-verify the corrected output
        re_result = await run_verification(
            output=corrected.output,
            task=event.task,
            schema=event.schema_definition,
            ground_truth=event.ground_truth,
            conversation_history=event.conversation_history,
            config=config,
        )

        attempts.append(CorrectionAttempt(
            layer=layer,
            corrected_output=corrected.output,
            verification={...},
            success=re_result.action == "pass",
            ...
        ))

        if re_result.action == "pass":
            result.correction = CorrectionResult(
                corrected=True, final_output=corrected.output, attempts=attempts,
            )
            result.confidence = re_result.confidence
            result.action = "pass"
            return result

        # Escalate to next layer
        layer = min(layer + 1, 3)

    # All attempts failed — block
    result.action = "block"
    result.correction = CorrectionResult(corrected=False, ...)
    return result
```

### Redis Event Updates

Verified stream events gain correction metadata:

```python
verified_data = {
    "execution_id": ...,
    "agent_id": ...,
    "confidence": ...,
    "action": ...,
    "checks": ...,
    "corrected": str(response.corrected),
    "correction_attempts": json.dumps(attempts),
}
```

---

## SDK Integration

### Transport (`sdk/python/agentguard/transport.py`)

`SyncTransport.verify()` forwards correction + transparency settings in metadata and uses a longer timeout client when correction is enabled:

```python
class SyncTransport:
    def __init__(self, api_url, api_key, timeout_s=2.0, correction_timeout_s=12.0):
        self.timeout_s = timeout_s
        self.correction_timeout_s = correction_timeout_s
        self._default_client = httpx.Client(timeout=timeout_s, headers=...)
        self._correction_client: Optional[httpx.Client] = None

    def _get_correction_client(self):
        if self._correction_client is None or self._correction_client.is_closed:
            self._correction_client = httpx.Client(
                timeout=self.correction_timeout_s,
                headers={"X-AgentGuard-Key": self.api_key},
            )
        return self._correction_client

    def verify(self, event, thresholds=None, correction="none", transparency="opaque"):
        client = (self._get_correction_client()
                  if correction == "cascade" else self._default_client)

        payload = event.model_dump(mode="json")
        if payload.get("metadata") is None:
            payload["metadata"] = {}
        payload["metadata"]["correction"] = correction
        payload["metadata"]["transparency"] = transparency

        if thresholds is not None:
            payload["metadata"]["thresholds"] = {
                "pass_threshold": thresholds.pass_threshold,
                "flag_threshold": thresholds.flag_threshold,
            }

        response = client.post(f"{self.api_url}/v1/verify", json=payload)
        response.raise_for_status()
        return response.json()
```

### Guard Client (`sdk/python/agentguard/guard.py`)

`_process_event()` maps server response to `GuardResult`:

```python
async def _process_event(self, event):
    if self.config.mode == "sync":
        result = self._sync_transport.verify(
            event,
            thresholds=self.config.confidence_threshold,
            correction=self.config.correction,
            transparency=self.config.transparency,
        )

        corrected = result.get("corrected", False)
        output = result.get("output", event.output) if corrected else event.output

        guard_result = GuardResult(
            output=output,
            confidence=result.get("confidence"),
            action=result.get("action", "pass"),
            execution_id=event.execution_id,
            verification=result.get("checks"),
            corrected=corrected,
            original_output=result.get("original_output") if corrected else None,
            corrections=result.get("correction_attempts"),
        )

        if guard_result.action == "block":
            raise AgentGuardBlockError(guard_result)
        if guard_result.action == "flag":
            logger.warning("Verification flagged: confidence=%.2f",
                           guard_result.confidence or 0)
        return guard_result
```

### User-Facing API

```python
# Without correction (default — existing behavior, zero changes)
guard = AgentGuard(api_key="...", config=GuardConfig(mode="sync"))

# With correction enabled
guard = AgentGuard(
    api_key="...",
    config=GuardConfig(
        mode="sync",
        correction="cascade",
        transparency="opaque",  # or "transparent"
    ),
)

with guard.session(agent_id="my-agent") as session:
    with session.trace(input=question, task="answer") as ctx:
        answer = my_agent(question)
        ctx.set_output(answer)

    # ctx.result.output      → corrected output (if correction happened)
    # ctx.result.corrected   → True/False
    # ctx.result.action      → "pass" (if corrected successfully)
    # ctx.result.corrections → attempt list (transparent mode only)
```

---

## Database Migration

```sql
-- Migration 006: Add correction tracking to executions
ALTER TABLE executions ADD COLUMN corrected BOOLEAN DEFAULT FALSE;
CREATE INDEX idx_executions_corrected ON executions (org_id, corrected) WHERE corrected = TRUE;
```

Correction attempt details stored in existing `executions.metadata` JSON column. No new tables needed.

### Storage Worker Update

`process_verified_event` extracts correction metadata from Redis stream:

- `executions.corrected = true/false`
- `executions.metadata.correction_attempts = [...]`
- `executions.metadata.original_output` preserved when corrected

---

## Dashboard Changes

### Trace Detail Page (`/agents/[agentId]/traces/[executionId]`)

New **Correction Timeline** section (only shown when corrected):

- Each attempt: layer name, confidence after re-verify, action, latency
- Expandable corrected output per attempt
- Green checkmark on success, red X on failure

**Output Diff** component: inline diff of original vs corrected output (red/green lines). JSON outputs pretty-printed before diff.

### Fleet Overview (`/agents`)

New **Correction Rate** metric:
- `COUNT(corrected=true) / COUNT(action IN ('flag','block') OR corrected=true)`
- Color coded: >80% green, 50-80% amber, <50% red

### Agent Detail (`/agents/[agentId]`)

New correction stats:
- Corrections (24h), Correction Success Rate
- Avg Correction Latency
- Layer Distribution (mini bar chart)

### Failures Page (`/agents/failures`)

- New "Corrected" column (Yes/No badge)
- New "Corrected" filter option (All, Corrected, Uncorrected)

---

## Build Order

```
Task 1:  DB Migration — ALTER executions ADD corrected BOOLEAN
Task 2:  Engine correction module (select_layer, L1, L2, L3)         ← no deps
Task 3:  Engine models (CorrectionAttempt, CorrectionResult)          ← parallel with T2
Task 4:  Shared models (CorrectionAttemptResponse, VerifyResponse)    ← parallel with T2
Task 5:  Gateway orchestration (correction loop, 10s timeout)         ← depends T2-T4
Task 6:  Storage worker (persist corrected flag + metadata)           ← depends T1, T4
Task 7:  SDK transport (correction forwarding, dual timeout)          ← depends T4
Task 8:  SDK models + guard client (GuardResult, _process_event)      ← depends T7
Task 9:  Dashboard (CorrectionTimeline, OutputDiff, metrics, filters) ← depends T1, T6
Task 10: Integration tests                                            ← depends T5-T8
Task 11: Live LLM test                                                ← depends all
```

Parallelizable: Tasks 2, 3, 4 run in parallel. Tasks 6, 7 run in parallel after deps.

---

## Testing Strategy

### Unit Tests (~45 new)

| Component | Tests | Focus |
|---|---|---|
| Engine correction module | 12 | select_layer routing, L1/L2/L3 output, LLM timeout/malformed handling |
| Engine models | 3 | CorrectionAttempt/CorrectionResult validation, serialization |
| Gateway orchestration | 8 | No-correction unchanged, L1 succeeds, L1→L2 escalation, all fail→block, timeout, re-verify, original-only, Redis metadata |
| Shared models | 3 | CorrectionAttemptResponse, VerifyResponse with/without correction |
| SDK transport | 4 | Forwarding metadata, dual client timeouts, client selection |
| SDK guard client | 6 | Corrected output mapping, opaque/transparent modes, block on failure, async ignores correction |
| SDK models | 2 | GuardResult new fields, backward compat |
| Storage worker | 3 | Persist corrected=true, no correction→false, original_output preserved |

### Integration Tests (~4 new)

1. Sync + correction succeeds (L1)
2. Sync + correction escalates (L1→L2)
3. Sync + correction fails → AgentGuardBlockError
4. Sync + no correction → identical to Phase 2 (regression)

### Live LLM Tests (~3 new)

1. Schema violation → L1 repair fixes → passes
2. Hallucination → L2 regenerates with ground truth → passes
3. Uncorrectable output → all layers fail → block

### Expected Test Totals

| Component | Before | New | After |
|---|---|---|---|
| Engine | 49 | 15 | 64 |
| Gateway | 7 | 8 | 15 |
| Shared | 22 | 3 | 25 |
| SDK | 60 | 12 | 72 |
| Storage | 12 | 3 | 15 |
| Integration | 6 | 4 | 10 |
| **Total** | **156** | **45** | **~201** |

---

## What Does NOT Change

- Async mode (`mode="async"`) — no correction, fire-and-forget unchanged
- Async worker — processes raw events, no correction logic
- Engine `verify()` signature — unchanged, no correction awareness
- `Session` conversation history accumulation — unchanged
- Non-session `guard.trace()` — works the same
- Default behavior (`correction="none"`) — zero impact on existing users
- Alert service — continues to fire on block actions (including post-correction blocks)
