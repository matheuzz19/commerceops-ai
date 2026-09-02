# CommerceOps AI

CommerceOps AI is a spec-driven, production-oriented multi-agent business operations platform for Sales, Inventory, Finance, and General support workflows.

The source of truth is [docs/specs/COMMERCEOPS_AI_SPEC.md](docs/specs/COMMERCEOPS_AI_SPEC.md). Implementation should follow the milestones in that document in order.

## Current Status

This repository is organized for M0/M1 development:

- Python package skeleton under `src/commerceops`
- FastAPI health entrypoint placeholder
- Docker Compose services for API, MCP server, PostgreSQL, and Redis
- Test, eval, docs, and agent-workflow directories
- Development-agent instructions in `AGENTS.md` and `.agents/`

## Local Development

```powershell
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
python -m pip install -e ".[dev]"
python -m pytest
```

CI runs the same deterministic checks on GitHub Actions:

```powershell
ruff check .
mypy src
pytest tests/unit tests/integration tests/contract tests/evals
docker build --pull --tag commerceops-ai:ci .
```

Run the API locally:

```powershell
uvicorn commerceops.api.main:app --reload
```

Run the full local stack:

```powershell
docker compose up --build
```

## Required Environment

Copy `.env.example` to `.env` for local development. Do not commit secrets or client-specific material.

## Architecture

See [docs/architecture.md](docs/architecture.md).

## Decisions

Architecture decisions live in [docs/decisions](docs/decisions).

## Safety Boundary

This project must remain sanitized. Do not add:

- real credentials, API keys, webhook URLs, provider endpoints, or database URLs
- client names, phone numbers, contacts, products, orders, inventory, or transaction data
- raw prompts or implementation labels from any external workflow reference
- WhatsApp-specific or Evolution API logic
