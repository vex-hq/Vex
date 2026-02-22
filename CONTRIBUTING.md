# Contributing to Vex

Thanks for your interest in contributing to Vex. Every contribution matters — whether it's a bug report, a documentation fix, or a new feature.

## Ways to Contribute

- **Bug reports** — File an issue with a clear description and reproduction steps.
- **Feature requests** — Open an issue describing the use case and expected behavior.
- **Code** — Fix bugs, implement features, or improve performance.
- **Documentation** — Improve guides, fix typos, or add examples.

## Development Setup

```bash
git clone --recurse-submodules https://github.com/Vex-AI-Dev/Vex.git
cd Vex
```

### Services (Python)

- Python 3.9+
- Create a virtual environment and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Dashboard (TypeScript)

- Node.js 18+
- pnpm (the dashboard is a pnpm monorepo)

```bash
cd Dashboard
pnpm install
pnpm dev
```

## Code Style

### Python

- Formatter: **black**
- Linter: **ruff**
- Follow PEP 8
- Use type hints for all function signatures
- Write tests for new functionality

### TypeScript

- Formatter: **prettier**
- Enable **strict** mode in `tsconfig.json`
- Write tests for new functionality

## Pull Request Process

1. Fork the repository and create a branch from `main`.
2. Make your changes.
3. Ensure all tests pass.
4. Open a pull request describing **what** you changed and **why**.

Keep PRs focused — one logical change per PR.

## Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add rate-limit policy engine
fix: resolve token counting overflow on streaming responses
chore: update CI dependencies
docs: add SDK quickstart guide
```

## Licensing

Vex is dual-licensed:

- **SDK contributions** (Python-SDK, Typescript-sdk) are licensed under **Apache 2.0**.
- **Engine contributions** (Vex core, services) are licensed under **AGPLv3**.

By submitting a pull request to AGPLv3-licensed components, you agree that Vex AI, Inc. may dual-license your contribution under commercial terms in addition to AGPLv3.

## Code of Conduct

All participants are expected to follow our [Code of Conduct](CODE_OF_CONDUCT.md).
