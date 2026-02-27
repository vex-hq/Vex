# Verification Engine

Shared library providing deterministic and LLM-based verification checks for agent output quality.

## Responsibilities

- Orchestrates a multi-check verification pipeline with composite confidence scoring
- **Schema validation** — deterministic JSON Schema compliance check
- **Hallucination detection** — LLM-based factual consistency scoring against ground truth
- **Drift scoring** — LLM-based task relevance evaluation
- **Coherence checking** — LLM-based cross-turn consistency (when conversation history is provided)
- **Tool loop detection** — deterministic detection of repetitive tool call patterns
- **Custom guardrails** — regex, keyword, threshold, and LLM-based rule evaluation
- **Correction cascade** — 3-layer graduated self-correction of failed outputs:
  - Layer 1 (Repair): small model, surgical fix of specific errors
  - Layer 2 (Constrained Regen): strong model, fresh output without seeing failed output
  - Layer 3 (Full Re-prompt): strong model, regeneration with explicit failure feedback
- Routes final action (`pass`, `flag`, `block`) based on configurable confidence thresholds

## Architecture

This is a library, not a standalone service. It is imported by:
- **sync-gateway** — for synchronous verification and correction
- **async-worker** — for asynchronous verification

## Dependencies

### External
- **LiteLLM** — model-agnostic LLM completions (supports OpenAI, Anthropic, and proxy routing)
- **jsonschema** — deterministic JSON Schema validation

### Internal
- None (this is a leaf dependency)

## Key Modules

| Module | Description |
|--------|-------------|
| `engine/pipeline.py` | Orchestrates all checks and computes composite confidence |
| `engine/schema_validator.py` | Deterministic JSON Schema validation |
| `engine/hallucination.py` | LLM-based factual consistency check |
| `engine/drift.py` | LLM-based task relevance scoring |
| `engine/coherence.py` | LLM-based cross-turn conversation consistency |
| `engine/tool_loop.py` | Deterministic tool call loop detection |
| `engine/guardrails.py` | Custom guardrail rule evaluation (regex, keyword, threshold, LLM) |
| `engine/correction.py` | 3-layer correction cascade |
| `engine/confidence.py` | Weighted composite confidence scorer |
| `engine/llm_client.py` | LiteLLM wrapper with JSON extraction and timeout handling |
| `engine/models.py` | Pydantic models for results, config, and correction attempts |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `VERIFICATION_MODEL` | No | LLM model for checks (default: `claude-haiku-4-5-20251001`) |
| `VERIFICATION_TIMEOUT_S` | No | Per-check LLM timeout in seconds (default: `5`) |
| `CORRECTION_REPAIR_MODEL` | No | Model for Layer 1 repair (default: `gpt-4o-mini`) |
| `CORRECTION_STRONG_MODEL` | No | Model for Layer 2-3 correction (default: `gpt-4o`) |
| `LITELLM_API_URL` | No | LiteLLM proxy base URL |
| `LITELLM_API_KEY` | No | LiteLLM proxy API key |
| `OPENAI_API_BASE` | No | OpenAI-compatible API base URL (fallback for `LITELLM_API_URL`) |
| `OPENAI_API_KEY` | No | OpenAI API key (fallback for `LITELLM_API_KEY`) |

## Installation

```bash
cd services/verification-engine
pip install -e ".[dev]"
```

## Testing

```bash
pytest tests/ -v
```
