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
docker compose --profile test up -d postgres-test redis-test
$env:TEST_DATABASE_URL = "postgresql+psycopg://commerceops:commerceops@localhost:5433/commerceops_test"
$env:TEST_REDIS_URL = "redis://localhost:6380/15"
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

The stack defines `agent-api`, `mcp-server`, `postgres`, and persistent `redis`.
M7 adds Redis-backed message buffering, graph checkpoints, session inspection,
and a lifespan worker. See `docs/m7-manual-test.md` for manual verification.
