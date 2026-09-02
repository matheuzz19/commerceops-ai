# CommerceOps AI

CommerceOps AI is a spec-driven commerce operations platform being built to
coordinate Sales, Inventory, Finance, and General workflows through LangGraph
and MCP. The project currently delivers the deterministic PostgreSQL backend
that those future agent workflows will use: tenant-scoped data access, explicit
business rules, database migrations, synthetic fixtures, and automated quality
gates.

> **Current status:** M1 Foundation and M2 Domain and Backend are complete. The
> public API currently exposes only `GET /health`; MCP tools, LangGraph agents,
> HITL, Redis buffering, observability, and deployment automation are planned
> milestones and are not functional yet.

The authoritative source for requirements and implementation decisions is the
[CommerceOps AI specification](docs/specs/COMMERCEOPS_AI_SPEC.md).

## Why this project matters

Agent behavior is only as trustworthy as the software beneath it. CommerceOps
AI is being developed from deterministic domain logic outward so that future
LLM-driven actions cannot bypass tenant boundaries, calculate financial values
in prompts, or report writes without confirmed tool results.

The current implementation demonstrates:

- A PostgreSQL domain model for customers, products, orders, inventory, and
  finance
- Tenant isolation enforced in repositories and services rather than delegated
  to prompts
- Server-side order totals and an auditable inventory movement ledger
- Alembic migrations and deterministic, idempotent seed data for two synthetic
  tenants
- PostgreSQL-only backend tests, strict type checking, linting, container builds,
  and migration checks in CI

## Architecture and delivery order

The runtime architecture is defined in [docs/architecture.md](docs/architecture.md).
The implementation itself follows this numerical milestone order; components
marked **implemented** exist today.

```text
M1  Foundation                         implemented
    FastAPI health endpoint, configuration, Docker Compose, CI
    |
    v
M2  Domain and backend                 implemented
    PostgreSQL, Alembic, tenant-scoped repositories, services, seed data
    |
    v
M3  MCP layer                          next
    MCP server/client, tool schemas, authorization, contract tests
    |
    v
M4  LangGraph core                     planned
    Typed state, message normalization, router, general node
    |
    v
M5  Specialist workflows               planned
    Sales, Inventory, Finance, entity resolution, tool verification
    |
    v
M6  Policy and HITL                    planned
    Risk policy, approvals, interrupt and resume
    |
    v
M7  Buffering and checkpointing        planned
    Redis message aggregation and persisted session state
    |
    v
M8  Testing, evals, observability      planned
    Agent evaluation, traces, structured logs, metrics
    |
    v
M9  Deployment and portfolio packaging planned
    Production deployment, documentation, demo, limitations
```

The target runtime flow is FastAPI -> LangGraph -> policy -> MCP -> deterministic
services -> PostgreSQL. Redis supports buffering and checkpointing when M7 is
implemented.

## Implemented backend capabilities

The current service layer supports deterministic operations that will later be
exposed through MCP contracts:

- **Customers:** create, get, and search within a tenant
- **Products:** create, get, and search active tenant-owned products
- **Orders:** create, list, and update orders using tenant-owned customers and
  products; totals are calculated from persisted product prices
- **Inventory:** record and list movements, aggregate current stock, and reject
  outbound movements that would create negative stock
- **Finance:** record and list transactions and calculate date-range summaries
  from posted transactions

These are Python service capabilities, not public HTTP or MCP endpoints yet.

## Safety and data integrity

- Every business entity except `Tenant` includes `tenant_id`.
- Repository reads require a trusted `tenant_id` and add it to the database
  query.
- Cross-tenant records are treated as not found, including references used in
  write operations.
- Order totals are calculated server-side from active, tenant-owned products.
- Inventory is derived from `IN`, `OUT`, and `ADJUSTMENT` ledger entries instead
  of a mutable stock counter.
- Financial summaries include only `POSTED` transactions.
- Domain failures use explicit error codes such as `CUSTOMER_NOT_FOUND` and
  `INSUFFICIENT_STOCK`.

High-risk approval, batch-write limits, specialist tool authorization, and
schema-validated MCP inputs and outputs belong to M3 and M6; the README does not
claim those runtime controls are implemented today.

## Technology choices

| Technology | Role in the project |
| --- | --- |
| Python 3.11+ and FastAPI | Typed application code and HTTP boundary |
| SQLAlchemy 2 and Alembic | ORM persistence and versioned schema migrations |
| PostgreSQL 16 | Business data and PostgreSQL-backed verification |
| Redis 7 | Provisioned locally for future buffering and checkpoints |
| LangGraph and MCP | Installed dependencies reserved for upcoming agent and tool layers |
| Pydantic Settings | Environment-based configuration |
| Pytest, Ruff, and Mypy | Tests, linting, and strict static type checking |
| Docker Compose and GitHub Actions | Reproducible local services and CI quality gates |

## Repository structure

```text
src/commerceops/
  api/             FastAPI application; currently the health route
  domain/          SQLAlchemy models, enums, and invariants
  repositories/    Tenant-scoped PostgreSQL access
  services/        Deterministic business operations
  db/              Session management and synthetic seed data
  mcp/             M3 placeholders
  graph/           M4+ placeholders
  observability/   M8 placeholders
alembic/            Migration environment and revisions
tests/              PostgreSQL-backed backend and health tests
docs/               Specification, architecture, decisions, and guides
```

## Local development

### Prerequisites

- Python 3.11 or newer
- Docker Desktop with Docker Compose

### Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

The example environment file contains development defaults only. Do not add or
commit real credentials.

### Start PostgreSQL, Redis, and the API

```powershell
docker compose up -d postgres redis
docker compose run --rm agent-api alembic upgrade head
docker compose up --build agent-api
```

Verify the only current public endpoint:

```powershell
Invoke-RestMethod http://localhost:8000/health
```

Expected response:

```json
{"status":"ok"}
```

The `mcp-server` Compose service is a keep-alive placeholder until M3 and should
not be treated as a working MCP implementation.

## Database migrations

Alembic is the source of truth for creating the PostgreSQL schema. With the
Compose configuration, run migrations inside the API container:

```powershell
docker compose run --rm agent-api alembic upgrade head
```

When using a locally installed PostgreSQL instance, set `DATABASE_URL` for that
database and run:

```powershell
alembic upgrade head
```

## Tests and quality gates

Backend tests intentionally require PostgreSQL. The test configuration rejects
SQLite and any database not named `commerceops_test`, reducing the risk of
running destructive schema setup against a development database.

```powershell
docker compose --profile test up -d postgres-test
$env:TEST_DATABASE_URL = "postgresql+psycopg://commerceops:commerceops@localhost:5433/commerceops_test"
python -m pytest tests/unit tests/integration tests/contract tests/evals
docker compose --profile test stop postgres-test
```

Current tests cover the health route, inventory ledger aggregation and negative
stock rejection, server-side order totals, cross-tenant access rejection,
posted-only financial summaries, and idempotent multi-tenant seed data.

Run the remaining CI checks locally:

```powershell
python -m ruff check .
python -m mypy src
docker build --pull --tag commerceops-ai:ci .
```

GitHub Actions installs the project, runs Ruff and Mypy, provisions PostgreSQL,
applies `alembic upgrade head`, runs the test suites, and builds the container
image.

## Milestone roadmap

| Milestone | Deliverable | Status |
| --- | --- | --- |
| M1 | Packaging, configuration, health API, Docker Compose, CI foundation | Complete |
| M2 | PostgreSQL models, migrations, repositories, services, seed data | Complete |
| M3 | MCP server/client, tool schemas, authorization matrix, contract tests | Next |
| M4-M5 | LangGraph core and specialist workflows | Planned |
| M6 | Policy engine and human-in-the-loop approval | Planned |
| M7 | Redis buffering and checkpoint persistence | Planned |
| M8 | Agent evals, tracing, structured logs, and metrics | Planned |
| M9 | Deployment and portfolio packaging | Planned |

## Current limitations and non-goals

- The API does not yet expose commerce workflows.
- The MCP server and client are placeholders; there are no MCP tool contracts.
- LangGraph routing, specialist agents, entity resolution, and tool-result
  verification are not implemented.
- Redis is available in Compose but is not connected to message buffering or
  checkpoints.
- HITL, agent evaluation datasets, tracing, metrics, and deployment automation
  remain roadmap work.
- The MVP deliberately excludes a frontend, mobile app, WhatsApp, Kafka,
  Kubernetes, RAG, and integrations with real business systems.

## Project documentation

- [Authoritative specification](docs/specs/COMMERCEOPS_AI_SPEC.md)
- [Target architecture](docs/architecture.md)
- [Development guide](docs/development.md)
- [Evaluation plan](docs/evaluation.md)
- [Operations notes](docs/operations.md)
- [Architecture decisions](docs/decisions/)

This repository is a sanitized implementation. It must contain only synthetic
data and generic prompts—never real client data, credentials, private endpoints,
or client-specific workflow logic.
