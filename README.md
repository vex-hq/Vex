# Vex

**The reliability layer for AI agents in production.**

[![License: Apache 2.0](https://img.shields.io/badge/SDKs-Apache%202.0-blue.svg)](./LICENSING.md)
[![License: AGPL v3](https://img.shields.io/badge/Engine-AGPLv3-blue.svg)](./LICENSING.md)
[![PyPI](https://img.shields.io/pypi/v/vex-sdk)](https://pypi.org/project/vex-sdk/)
[![npm](https://img.shields.io/npm/v/@vex_dev/sdk)](https://www.npmjs.com/package/@vex_dev/sdk)
[![Docs](https://img.shields.io/badge/docs-docs.tryvex.dev-brightgreen)](https://docs.tryvex.dev)

## What is Vex?

Vex observes agent behavior, verifies outputs against guardrails, and auto-corrects hallucinations before they reach users — silently. It sits between your AI agent and end users, ensuring every response is grounded, safe, and policy-compliant without adding friction to the user experience.

## Key Capabilities

- **Observe** — Track every agent action, tool call, and LLM response in real time.
- **Verify** — Check outputs against configurable guardrails: hallucination detection, PII filtering, off-topic rejection, and tool-use policy enforcement.
- **Correct** — Auto-correct bad outputs before they reach users. The user never sees the hallucination.
- **Alert** — Get real-time notifications on behavioral drift, anomalies, and cost/latency spikes.

## Quick Start

```bash
pip install vex-sdk
```

```python
from vex_sdk import Vex

vex = Vex(api_key="your-api-key")

response = vex.verify(
    agent_id="support-bot",
    output="The refund policy allows returns within 30 days.",
    context={"source": "policy-doc-v2"}
)

print(response.verified_output)
```

See the [full documentation](https://docs.tryvex.dev) for TypeScript examples, guardrail configuration, and integration guides.

## Repository Structure

| Path | Description | License |
|------|-------------|---------|
| [`Dashboard/`](./Dashboard) | Next.js dashboard and landing page | AGPL-3.0 |
| [`sdk/python/`](./sdk/python) | Python SDK (`vex-sdk` on PyPI) | Apache-2.0 |
| [`sdk/typescript/`](./sdk/typescript) | TypeScript SDK (`@vex_dev/sdk` on npm) | Apache-2.0 |
| [`services/`](./services) | Backend microservices | AGPL-3.0 |

**Services** include: ingestion-api, verification-engine, alert-service, sync-gateway, storage-worker, async-worker, and a shared library.

## Self-Hosting

Vex can be self-hosted on your own infrastructure. See the [self-hosting guide](https://docs.tryvex.dev/self-hosting) for setup instructions, configuration options, and deployment recommendations.

## Managed Cloud

For a fully managed experience, sign up at [app.tryvex.dev](https://app.tryvex.dev). The managed cloud includes automatic updates, built-in monitoring, and zero infrastructure overhead.

## Licensing

Vex uses a dual-license model:

- **SDKs** (Python, TypeScript) — [Apache License 2.0](./LICENSING.md)
- **Dashboard and Services** — [GNU AGPL v3](./LICENSING.md)

See [LICENSING.md](./LICENSING.md) for full details.

## Contributing

We welcome contributions. Please read [CONTRIBUTING.md](./CONTRIBUTING.md) for guidelines on development setup, pull requests, and code standards.

## Links

- [Documentation](https://docs.tryvex.dev)
- [Website](https://tryvex.dev)
- [Managed Cloud](https://app.tryvex.dev)
- [Twitter](https://x.com/tryvex)
