# Development Guide

Use this guide with the source specification in `docs/specs/COMMERCEOPS_AI_SPEC.md`.

## Setup

```powershell
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
python -m pip install -e ".[dev]"
```

## Checks

```powershell
ruff check .
mypy src
pytest tests/unit tests/integration tests/contract tests/evals
docker build --pull --tag commerceops-ai:ci .
```

Agent evals will be added in M8 and should run separately from deterministic tests.

## Implementation Order

Follow the milestone order from the spec. Do not start LangGraph specialist behavior before the deterministic backend, repositories, services, and MCP contracts are in place.

## Branch Hygiene

- Keep commits milestone-scoped.
- Prefer small PRs with tests.
- Do not mix formatting-only churn with behavioral changes.
- Preserve sanitized, synthetic data only.

## Local Services

```powershell
docker compose up --build
```

The initial scaffold defines `agent-api`, `mcp-server`, `postgres`, and `redis`. The MCP server command is intentionally a placeholder until M3.
