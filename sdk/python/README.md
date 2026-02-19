[![PyPI](https://img.shields.io/pypi/v/vex-sdk)](https://pypi.org/project/vex-sdk/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/Vex-AI-Dev/Python-SDK)](https://github.com/Vex-AI-Dev/Python-SDK)
[![Docs](https://img.shields.io/badge/docs-docs.tryvex.dev-brightgreen)](https://docs.tryvex.dev)

# Vex Python SDK

**Your AI agent doesn't crash. It drifts.** Vex is the runtime reliability layer that detects when your agent's behavior silently changes in production — before your customers notice.

The agent passes all evals. Ships to production. Works great for a week. Then slowly starts producing subtly different outputs. No error. No crash. No alert. Just quietly doing 90% of the job instead of 100%.

Vex catches that moment.

## What it does

- **Drift Detection** — knows what "normal" looks like for your agent and catches when behavior shifts
- **Execution Tracing** — auto-capture input/output/latency with decorators. Zero changes to your agent code
- **Sync Verification** — real-time pass/flag/block decisions with configurable confidence thresholds
- **Correction Cascade** — auto-repairs unreliable outputs instead of just blocking them

## See it in action

```bash
pip install vex-sdk
```

```python
from vex import Vex, VexConfig

guard = Vex(
    api_key="your-api-key",
    config=VexConfig(mode="sync", api_url="https://api.tryvex.dev"),
)

@guard.watch(agent_id="support-bot")
def handle_ticket(query: str) -> str:
    return call_llm(query)

result = handle_ticket("How do I reset my password?")
print(result.action)      # "pass" | "flag" | "block"
print(result.confidence)   # 0.92

# If the agent's response drifts from its baseline behavior,
# Vex flags it before your customer sees it.
```

## Why Vex?

| | Evals / Testing | Tracing (LangSmith etc.) | **Vex** |
|---|---|---|---|
| When | Before deployment | After something breaks | **Continuously in production** |
| What it tells you | "Agent was good" | "Here's what happened" | **"Agent just changed"** |
| Catches drift? | No | No | **Yes** |

Most monitoring tells you the agent ran. Vex tells you the agent changed.

## Detailed Usage

### Quick Start

```python
from vex import Vex, VexConfig

guard = Vex(
    api_key="your-api-key",
    config=VexConfig(api_url="https://api.tryvex.dev"),
)

# 1. Decorator — auto-capture input/output/latency
@guard.watch(agent_id="my-agent")
def run_agent(prompt: str) -> str:
    return call_llm(prompt)

# 2. Context manager — fine-grained step tracing
with guard.trace(agent_id="my-agent", task="summarize") as ctx:
    result = call_llm(prompt)
    ctx.step("llm", "summarize", input=prompt, output=result)
    ctx.record(result)
```

### Sync Verification

Run inline verification with pass/flag/block decisions. When the verification engine determines an output is unreliable, the SDK raises `VexBlockError` so your application can handle it gracefully.

```python
from vex import Vex, VexConfig, VexBlockError

guard = Vex(
    api_key="your-api-key",
    config=VexConfig(
        mode="sync",
        api_url="https://api.tryvex.dev",
    ),
)

@guard.watch(agent_id="my-agent")
def run_agent(prompt: str) -> str:
    return call_llm(prompt)

try:
    result = run_agent("Summarize this document")
    # result is a VexResult with confidence score
    print(result.output, result.confidence, result.action)
except VexBlockError as e:
    print(f"Blocked: confidence={e.result.confidence}")
```

### Correction Cascade

Automatically correct unreliable outputs instead of blocking. When enabled, the verification engine attempts to fix issues and returns the corrected output.

```python
guard = Vex(
    api_key="your-api-key",
    config=VexConfig(
        mode="sync",
        correction="cascade",          # Enable correction
        transparency="transparent",    # Include correction details in result
    ),
)

result = run_agent("Summarize this document")
if result.corrected:
    print(f"Output was corrected: {result.output}")
    print(f"Original: {result.original_output}")
```

### Session Tracking & Conversation History

Group related executions into sessions with automatic conversation history for multi-turn verification (hallucination, drift, coherence).

```python
session = guard.session(agent_id="chat-bot")

# Turn 1
with session.trace(task="greeting", input_data="Hello") as ctx:
    response = call_llm("Hello")
    ctx.record(response)

# Turn 2 — conversation history from turn 1 is sent automatically
with session.trace(task="follow-up", input_data="Tell me more") as ctx:
    response = call_llm("Tell me more")
    ctx.record(response)
```

The session maintains a sliding window of conversation history (configurable via `conversation_window_size`), enabling cross-turn verification checks like self-contradiction detection and goal drift analysis.

## Integrations

Vex works with any AI agent framework. Drop it into:

- **LangChain / LangGraph** agents
- **CrewAI** crews
- **OpenAI Assistants** / function calling
- **Custom agents** — any Python function that calls an LLM

No framework lock-in. If your code calls an LLM, Vex can watch it.

## Configuration

```python
from vex import VexConfig
from vex.models import ThresholdConfig

VexConfig(
    mode="async",               # "async" (fire-and-forget) or "sync" (inline verification)
    correction="none",          # "none" or "cascade" (auto-correct unreliable outputs)
    transparency="opaque",      # "opaque" or "transparent" (include correction details)
    api_url="https://api.tryvex.dev",
    flush_interval_s=1.0,       # Batch flush interval (async mode)
    flush_batch_size=50,        # Max events per flush batch
    timeout_s=2.0,              # HTTP timeout for API calls
    conversation_window_size=10,  # Max conversation turns retained per session
    confidence_threshold=ThresholdConfig(
        pass_threshold=0.8,     # >= 0.8 → pass
        flag_threshold=0.5,     # >= 0.5 → flag (warning logged)
        block_threshold=0.3,    # < 0.3 → block (raises VexBlockError)
    ),
)
```

## Get Started

1. `pip install vex-sdk`
2. Get your API key at [tryvex.dev](https://tryvex.dev)
3. Add `@guard.watch()` to your agent function
4. Deploy. Vex learns what "normal" looks like and alerts you when it changes.

Full docs: [docs.tryvex.dev](https://docs.tryvex.dev)

## What's New in v0.3.0

- **Rebranded to Vex**: `pip install vex-sdk`, `from vex import Vex, VexConfig`
- **Sync Verification**: Inline pass/flag/block decisions via `mode="sync"` with configurable confidence thresholds
- **Correction Cascade**: Auto-correct unreliable outputs with `correction="cascade"`, dual-timeout transport (2s verify / 12s correction), and transparent/opaque modes
- **Conversation-Aware Verification**: Multi-turn coherence, cross-turn hallucination detection, and goal drift analysis via automatic session history
- **`VexResult` Model**: Structured verification results with `confidence`, `action`, `corrected`, `original_output`, and `corrections` fields
- **`VexBlockError`**: Exception raised when verification blocks output, with the full `VexResult` attached
- **`ConversationTurn` Model**: First-class conversation turn representation for multi-turn agents

## Contributing

We welcome contributions. See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

If you find Vex useful, consider starring this repo — it helps others discover it.

## Links

- Website: [tryvex.dev](https://tryvex.dev)
- Docs: [docs.tryvex.dev](https://docs.tryvex.dev)
- Twitter: [@7hakurg](https://x.com/7hakurg)
- Issues: [GitHub Issues](https://github.com/Vex-AI-Dev/Python-SDK/issues)

## Requirements

- Python 3.9+
- Dependencies: `httpx`, `pydantic` (v2)

## License

Apache 2.0 — see [LICENSE](LICENSE) for details.
