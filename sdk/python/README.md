# AgentGuard Python SDK

The reliability layer for AI agents in production. Trace executions, enforce guardrails, and monitor agent behavior — with zero changes to your agent's core logic.

## Installation

```bash
pip install agentguard
```

## Quick Start

```python
from agentguard import AgentGuard, GuardConfig

guard = AgentGuard(
    api_key="your-api-key",
    config=GuardConfig(api_url="https://api.agentguard.dev"),
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

# 3. Session — group related executions
session = guard.session(agent_id="chat-bot")
with session.trace(task="turn 1", input_data=user_msg) as ctx:
    response = call_llm(user_msg)
    ctx.record(response)
```

## Configuration

```python
GuardConfig(
    mode="async",           # "async" (fire-and-forget) or "sync" (inline verification)
    api_url="https://api.agentguard.dev",
    flush_interval_s=1.0,   # Batch flush interval (async mode)
    flush_batch_size=50,    # Max events per flush batch
    timeout_s=2.0,          # HTTP timeout for API calls
)
```

## Requirements

- Python 3.9+
- Dependencies: `httpx`, `pydantic` (v2)

## Documentation

Full documentation: [docs.oppla.ai/agentguard](https://docs.oppla.ai/agentguard)

## License

Apache 2.0 — see [LICENSE](LICENSE) for details.
