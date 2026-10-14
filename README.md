# CommerceOps AI

CommerceOps AI is a spec-driven commerce operations platform being built to
coordinate Sales, Inventory, Finance, and General workflows through LangGraph
and MCP. The project delivers specialist agent workflows, a deterministic PostgreSQL
backend, schema-validated MCP tools, policy-driven human approval, durable Redis
sessions, and evaluation/observability instrumentation. Tenant boundaries and
write validation are enforced in application code.

> **Current status:** M1 Foundation through M8 Testing, Evals and Observability are complete.
> The API aggregates debounced text in Redis, persists tenant-scoped session
> state and checkpoints, and resumes high-risk actions through trusted approval
> endpoints even after an API restart. M8 adds 131 evaluation cases, private traces,
> JSON logs and /metrics. M9 deployment and portfolio packaging are next.

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
M3  MCP layer                          implemented
    MCP server/client, tool schemas, authorization, contract tests
    |
    v
M4  LangGraph core                     implemented
    Typed state, normalization, Send-based router, general node
    |
    v
M5  Specialist workflows               implemented
    Sales, Inventory, Finance, entity resolution, tool verification
    |
    v
M6  Policy and HITL                    implemented
    Risk policy, approvals, interrupt and resume
    |
    v
M7  Buffering and checkpointing        implemented
    Redis message aggregation and persisted session state
    |
    v
M8  Testing, evals, observability      implemented
    Agent evaluation, traces, structured logs, metrics
    |
    v
M9  Deployment and portfolio packaging planned
    Reproducible deployment, documentation, demo, limitations
```

The target runtime flow is FastAPI -> LangGraph -> policy -> MCP -> deterministic
services -> PostgreSQL. Redis persists buffering, checkpoints, session ownership, and message receipts.

## Delivery history: problems, fixes, and evidence

The milestones were developed in numerical order, starting with deterministic
business behavior. This history distinguishes reproduced defects from preventive
controls. The repository does not document a separate failed experiment for M1–M3;
their rows describe the boundaries established and the evidence available.

| Phase | Delivered | What went wrong or needed correction | Resolution and evidence |
|---|---|---|---|
| M0 — Specification | Sanitized scope, invariants, authorization matrix, milestone order and ADRs | The reference automation contained client-specific material that could not be reused. | Reimplemented from a generic specification; only synthetic identities/data enter fixtures and documentation. |
| M1 — Foundation | FastAPI health endpoint, settings, Python package, lint/typecheck/tests, Docker Compose and CI | No milestone-specific incident is recorded. The setup needed one reproducible runtime and quality baseline. | Environment-based configuration, development-only example values and automated checks establish the baseline. |
| M2 — Domain/backend | PostgreSQL models, Alembic migrations, repositories, services and multi-tenant seed | No separate failed experiment is recorded. Unscoped queries, prompt-calculated money and mutable stock totals were explicit risks. | Tenant filters live in repositories/services; Decimal and server-side totals handle money; inventory uses a movement ledger. PostgreSQL tests verify invariants and tenant boundaries. |
| M3 — MCP | Typed server/client, tool contracts and specialist scopes | No milestone-specific incident is recorded. Model-provided tenant identity and unrestricted tools would bypass isolation. | Trusted runtime context supplies identity, schemas validate IO, and authorization is checked in code. Contract tests exercise valid/invalid inputs and rejected access. |
| M4 — LangGraph core | Structured routing, bounded tasks, parallel Send dispatch and deterministic aggregation | First live routing evaluation scored 29/40 (72.5%): missing execution details caused actionable requests to be sent to General. | Explicit ownership map and schema descriptions separate domain routing from missing arguments; General stays exclusive. Expanded baseline reached 41/41 (100%). |
| M5 — Specialists | Plan → resolve → execute → verify workflows for Sales, Inventory and Finance | Inventory needed product lookup in its granted scope. Ambiguous names and malformed success envelopes could otherwise lead to unsafe writes or false confirmations. | Granted the specification's search_products scope, resolved IDs through prior tool results, and validated tool-specific outputs. Missing/ambiguous entities stop writes; parallel workers use independent DB sessions. |
| M6 — Policy/HITL | Risk rules, batch policy, interrupt/resume and approval/rejection endpoints | Replaying interrupted planning could change amounts or entities after review. Competing approvals could repeat a write; multiple interrupts and reused reducers were mishandled; another branch could write before the complete batch was reviewed. | Saved proposals before interrupt, evaluated the whole request before writes, consumed handles atomically, resumed by interrupt ID and reset request collections with Overwrite. Added 16 regression cases; uncertain writes require inspection. |
| M7 — Durability | Redis debounce, source message IDs, session inspection, durable checkpoints/approvals and worker recovery | In-memory state could not survive restart. Concurrent/stale workers needed ownership checks. The Docker image omitted files required by the documented Alembic command. | Persisted the complete intake/session boundary; added renewable leases and token-checked updates; recovered saved outcomes without replaying uncertain writes; packaged migrations. Added 17 cases with real Redis and verified Alembic inside the image. |
| M8 — Evaluation/observability | Five datasets, replay/live runner, reports, JSON events, private traces and /metrics | Datasets beyond routing and telemetry modules were empty. Evaluation found SKU lookup searched only names, a Decimal transport schema broke live Finance planning, and planner fields were insufficiently explicit. The harness also shared one DB session across concurrent tool calls. | Added 131 cases and independent effect/provenance checks; extended tenant-scoped lookup to SKU; transported decimal strings while retaining Decimal validation; clarified planner fields; serialized harness access inside rollback-only fixtures. 109 tests and the 131-case replay passed. Live reached 100% routing/tool selection/task completion, 95% entity resolution and zero safety violations; divergences remain recorded in the M8 report. |
| M9 — Deployment/packaging | Planned | Final reproducibility review, evaluation presentation and demo script remain. | Validate the complete acceptance checklist from a clean database and package a runnable, understandable portfolio release. |

### Architecture choices and trade-offs

| Choice | Why it was selected | Trade-off or limit |
|---|---|---|
| Deterministic services under the agent | Business invariants, money and tenant isolation remain enforceable regardless of model output. | More explicit application code; the model cannot perform arbitrary operations. |
| PostgreSQL and an inventory ledger | Relational constraints, transactions and auditable movements fit commerce data. | Stock reads aggregate movements; PostgreSQL is required even for backend tests. |
| One MCP server with tool-level scopes | A common typed boundary with specialist least privilege and fewer deployment components. | Authorization mistakes affect a shared boundary; scopes need contract tests. The current graph adapter uses in-process MCP, so a deployed remote transport remains a separate concern. |
| Tool-free structured router and planners | Models identify intent; application code resolves IDs and validates execution. | Each request can need router and planner calls, adding latency/cost; schema compatibility and model quality need live evaluations. |
| LangGraph Send with reducer-backed fan-in | Independent domains can run concurrently, with predictable result ordering. | Parallel state needs explicit reducers, resets and a request-wide write barrier. |
| Saved batch proposals and one-use HITL handles | Approval refers to the displayed actions; competing decisions cannot reuse a handle. | Approval is for the whole batch, without per-action editing. Separate tools retain separate transactions; approval does not provide an atomic business rollback. |
| Plain Redis with a custom typed saver | Persists buffering, ownership, receipts and checkpoints without Redis Search/JSON modules. | Requires saver contract/compatibility tests; one Redis instance has no HA and checkpoints currently lack automatic retention. |
| Redis leases, fenced metadata updates and conservative recovery | Coordinates normal workers and prevents stale owners from overwriting session metadata. | Redis and PostgreSQL have no shared transaction. Exactly-once across both stores is not guaranteed; interrupted possible writes require inspection. AOF appendfsync always adds IO overhead. |
| Replay plus live evals | CI can reproduce execution/safety behavior without provider access; live runs measure model understanding separately. | Replay accuracy is fixture evidence, not model quality. Synthetic cases do not represent production traffic; live runs consume tokens and may vary. |
| Redacted LangSmith traces and bounded Prometheus labels | Paths, policy, tool outcomes, latency and available usage remain observable without exporting prompts or tool payloads. | Prompt/response inspection is unavailable in traces. Metrics are per process; multi-process aggregation requires a collector strategy. Cost depends on explicitly supplied rates. |

Decisions are explained in [the ADRs](docs/decisions/); validation results and
commands are in [the evaluation guide](docs/evaluation.md).

## M4: LangGraph multi-agent routing core

M4 introduces the first agent layer in CommerceOps AI. The supervisor follows a
router-worker multi-agent architecture built with LangChain and LangGraph:

```text
Normalized message
       |
       v
Structured LangChain router
       |
       v
LangGraph Send fan-out
       |
       +--> Sales specialist
       +--> Inventory specialist
       +--> Finance specialist
       +--> General specialist
                  |
                  v
       Reducer-backed aggregation
                  |
                  v
          Final response
```

The router uses an OpenAI model with structured output to produce a bounded list
of department-scoped tasks. LangGraph `Send` dynamically dispatches those tasks
to the selected specialist workers, allowing independent parts of a multi-domain
request to run in parallel.

For example, `Show this month's revenue and current keyboard stock` is
decomposed into separate Finance and Inventory tasks. Both specialists are
dispatched in the same graph fan-out, and their results are combined after every
branch completes.

The router has no tools and cannot perform business operations. Trusted tenant,
user, and session identity comes from graph runtime state and is copied into each
worker payload by application code, never generated by the model.

Parallel specialist outputs use a reducer-backed collection so concurrent state
updates do not overwrite one another. Results include their original task
position and are sorted before final response composition, producing
deterministic output even when workers finish in a different order.

General is an exclusive route. If a request is truly ambiguous, unsupported, or
only asks for help, the supervisor dispatches General without simultaneously
sending the request to an action-capable specialist.

M4 initially introduced safe specialist skeletons. M5 replaces them with typed
planning, entity resolution, MCP execution, and tool-result verification.

### Parallel write-intent safety

M4 includes a test for a cross-domain request such as:

```text
Confirm order ORD-100 and remove two keyboards from inventory
```

The graph dispatches both Sales and Inventory while proving that neither branch
creates tool results or proposed actions during M4.

M6 now aggregates saved write proposals and evaluates the complete request before
execution or review. This prevents writes before batch approval. Approved tools
still have separate service transactions, so a later tool failure can leave an
earlier approved write committed; there is no shared rollback across specialists.

### M4 routing evaluation

The routing dataset contains 41 sanitized cases covering:

- Sales, Inventory, Finance, and General requests
- Ambiguous and unsupported requests
- Two-specialist and three-specialist fan-out
- Parallel Sales and Inventory update intent

The initial live-model evaluation produced:

```text
Correct routes:   29/40
Routing accuracy: 72.5%
Required minimum: 90%
```

LangSmith traces showed a consistent classification problem: the router treated
missing execution details as routing ambiguity. Customer searches, order
cancellation, transaction listing, and incomplete inventory movements were
incorrectly routed to General even though their owning department was clear.

The router prompt and structured schema were corrected by:

- Defining an explicit ownership map for every department
- Separating routing ambiguity from missing execution arguments
- Requiring every relevant specialist for multi-domain requests
- Preventing General from appearing alongside another specialist
- Assigning missing IDs, names, dates, amounts, and confirmation details to the
  specialist workflow rather than the router
- Adding stronger descriptions to the structured routing fields

After correction, the expanded evaluation produced:

```text
Correct routes:   41/41
Routing accuracy: 100%
Required minimum: 90%
```

Both evaluation runs were traced through LangSmith. The active tracing project
is `commerceops-ai-m4`, with the tags `m4` and `routing-baseline`.

## M5: Specialist workflows

Sales, Inventory, and Finance now use tool-free structured planners followed by
deterministic execution nodes. A planner describes the requested operation using
a department-specific Pydantic schema; application code then validates required
fields, resolves referenced entities, selects the authorized MCP tool, and
verifies the tool-specific result schema before composing a response.

Sales supports customer creation and search, product search, customer-scoped
order listing, order creation, and safe order updates. Order creation always
resolves the customer and every product through prior MCP search results. The
workflow ignores invented identifiers and does not call `create_order` when an
entity is missing or ambiguous.

Inventory supports stock lookup, movement listing, and movement creation. Every
product-specific operation first resolves the product through `search_products`.
The Inventory authorization scope now includes that read tool, matching the
source-of-truth authorization matrix.

Finance supports deterministic monthly or explicit-date summaries, transaction
listing, and expense recording. Relative periods such as `this month` and
`last month` are calculated in application code using the configured tenant
timezone instead of trusting model-generated dates.

MCP responses are validated twice: first as the shared tool envelope and then as
the expected tool-specific data model. Failed calls and malformed success data
produce recoverable specialist errors and never produce a success claim.

## M6: Policy and human approval

Every specialist write is converted to a typed `ProposedAction` after required
entity resolution and before MCP execution. The deterministic policy engine
validates the trusted tenant context, specialist authorization, tool input
schema, entity provenance, configured batch limit, and risk classification.

Cancellation and refund-like order updates, large financial transactions,
large inventory movements, negative-stock movements, and requests proposing
more than five writes require explicit approval. LangGraph interrupts the
workflow before the write. Approval resumes the same checkpoint and rejection
returns a verified non-execution response. Negative stock is permitted only
when the resumed graph supplies a trusted runtime grant to MCP; that grant is
never part of model-generated tool arguments.

Write preparation and policy evaluation now checkpoint before the dedicated
review node. Resuming approval executes the captured arguments without calling
the planner or resolving entities again. Multi-department write proposals are
reviewed together before any business write; rejection prevents the whole
proposed batch from executing.

Approval handles are consumed atomically, scoped to the tenant and user, and
cannot be replayed by competing HTTP requests. The API exposes all pending
interrupt IDs and resumes them with explicit ID-scoped decisions. Per-request
collections use `Overwrite` when a thread is reused. See
[ADR 0006](docs/decisions/0006-stable-action-review.md) for the guarantees and limits.

M6 checkpoints are in-process and intentionally ephemeral. M7 replaces this
with Redis-backed persistence and adds debounced message aggregation.

## M7: Buffering and checkpointing

`debounce=true` stores text fragments in a tenant/session buffer until the
configured window expires. The API lifespan worker aggregates them into one
graph execution and preserves all source message IDs. `debounce=false` runs
immediately and flushes any earlier text fragments in that session.

Graph checkpoints, pending approvals, ownership, receipts, and session results
are stored in Redis. Renewable leases serialize work across runtime instances,
and token-checked metadata updates reject stale owners. Repeated message IDs
return their saved response; changed content under an existing ID is rejected.

`GET /sessions/{session_id}/state` exposes the current result and persisted graph
state only to the owning tenant and user. Restarted workers recover saved
outcomes and approvals; unfinished possible writes require inspection and are
never replayed automatically. Redis uses AOF persistence and a named volume.

M7 verification: **83 tests passed**, including **17 new buffer/Redis tests**.
See the [manual test guide](docs/m7-manual-test.md) and
[ADR 0007](docs/decisions/0007-redis-conversation-durability.md).

## M8: Evaluation and observability

M8 adds 131 synthetic cases across routing, tool selection, entity resolution,
task completion and policy/safety. The replay runner replaces model decisions
while executing the real graph, MCP contracts, services and PostgreSQL. Live mode
uses the configured router and specialist models. Both modes report case outcomes,
dataset hashes, SDK versions, latency, available tokens and configured costs.

Replay must match every reference. Live must meet the specification's quality
thresholds and zero-tolerance safety gates; divergences remain visible per case.
The harness verifies database effects and entity provenance, and rolls back every
scenario. It only accepts the isolated commerceops_test PostgreSQL database.

Observability includes correlated JSON events, graph/model/tool traces and a
Prometheus /metrics endpoint. Traces hide inputs/outputs and redact exception text
and model configuration; metadata retains paths, policy decisions, tool outcomes,
status, durations and available usage. Metric labels omit tenant/session IDs.

~~~powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://commerceops:commerceops@localhost:5433/commerceops_test"
python -m commerceops.evals.runner --mode replay --output evals/reports/replay.json
python -m commerceops.evals.runner --mode live --concurrency 4 --output evals/reports/live.json
(Invoke-WebRequest http://localhost:8000/metrics).Content
~~~

Live evaluation consumes provider tokens and requires local credentials. Cost is
unknown without explicitly configured rates; replay performance is not a live
model benchmark. Normal CI runs replay without provider keys; live runs are
available through an explicit workflow_dispatch option. The validated run passed 109 tests; live routing, tool selection and task completion
scored 100%, entity resolution 95%, with zero safety violations. Detailed results and
remaining model errors are in [the M8 report](docs/reports/m8-validation.md).

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

These capabilities are available through schema-validated MCP tools, but are
not public FastAPI endpoints yet.

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

Specialist tool authorization, schema-validated MCP inputs and outputs, risk
classification, batch enforcement, and approval-before-execution are runtime
controls implemented in application code.

## Technology choices

| Technology | Role in the project |
| --- | --- |
| Python 3.11+ and FastAPI | Typed application code and HTTP boundary |
| SQLAlchemy 2 and Alembic | ORM persistence and versioned schema migrations |
| PostgreSQL 16 | Business data and PostgreSQL-backed verification |
| Redis 7 | Buffers, checkpoints, receipts, ownership, and execution leases |
| LangChain and LangGraph | Structured routing, dynamic `Send` fan-out, parallel workers, and deterministic aggregation |
| MCP | Schema-validated, specialist-authorized business tool boundary |
| LangSmith | M4 router traces and live evaluation diagnostics |
| Pydantic Settings | Environment-based configuration |
| Pytest, Ruff, and Mypy | Tests, linting, and strict static type checking |
| Docker Compose and GitHub Actions | Reproducible local services and CI quality gates |

## Repository structure

```text
src/commerceops/
  api/             FastAPI messages, approval/rejection, and health routes
  domain/          SQLAlchemy models, enums, and invariants
  repositories/    Tenant-scoped PostgreSQL access
  services/        Deterministic business operations
  db/              Session management and synthetic seed data
  mcp/             MCP server/client, schemas, authorization, execution
  graph/           Typed state and Send-based multi-specialist routing
  observability/   Private traces, JSON events, Prometheus metrics
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

Verify the health endpoint:

```powershell
Invoke-RestMethod http://localhost:8000/health
```

Expected response:

```json
{"status":"ok"}
```

Submit an immediate request with trusted development identity headers:

```powershell
$headers = @{"X-Tenant-ID"="<tenant-uuid>"; "X-User-ID"="operator"}
$body = @{session_id="demo"; message_id="1"; content="Record a 1200 expense"; debounce=$false} | ConvertTo-Json
Invoke-RestMethod http://localhost:8000/messages -Method Post -Headers $headers -ContentType "application/json" -Body $body
```

When the response status is `requires_confirmation`, resume it through
`POST /confirmations/{checkpoint_id}/approve` or reject it through
`POST /confirmations/{checkpoint_id}/reject` with the same identity headers.

The `mcp-server` Compose service exposes Streamable HTTP on port `8001`. Tool
execution requires trusted tenant and specialist context supplied by the
application boundary; those values are never model-visible tool arguments.

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
docker compose --profile test up -d postgres-test redis-test
$env:TEST_DATABASE_URL = "postgresql+psycopg://commerceops:commerceops@localhost:5433/commerceops_test"
$env:TEST_REDIS_URL = "redis://localhost:6380/15"
python -m pytest tests/unit tests/integration tests/contract tests/evals
docker compose --profile test stop postgres-test redis-test
```

Current automated coverage includes:

- FastAPI health behavior
- Inventory ledger aggregation and negative-stock rejection
- Server-side order totals
- Cross-tenant read and write rejection
- Posted-only financial summaries
- Idempotent multi-tenant seed data
- All twelve MCP tool contracts
- Specialist authorization and trusted tenant context
- Structured MCP success and failure envelopes
- Normalized graph-state and structured routing-plan validation
- Duplicate specialist removal and exclusive General routing
- Router failure recovery and single-domain graph dispatch
- Parallel multi-domain `Send` fan-out
- Deterministic specialist-result aggregation
- Sales and Inventory update-intent fan-out without writes
- Policy scope, schema, resolution, threshold, and batch enforcement
- HITL interrupt, approval resume, rejection, and tenant-scoped checkpoints
- Approved negative-stock execution through a trusted MCP runtime grant
- Routing dataset validation and exact agent-set scoring

The verified M1-M4 results are:

```text
Complete pytest suite: 50 passed
Focused M4 suite:      12 passed
Focused M5 integration: 10 passed
Live routing baseline: 41/41 (100%)
Ruff:                  passed
Strict mypy:           passed
```

The M6 corrective verification passed **66 tests**, including PostgreSQL-backed
workflows and 16 approval/state regression cases. Ruff, strict Mypy, and the
Docker build also passed. Regression coverage includes changed planner outputs,
rejection, concurrent approvals, multi-action review, total batch limits,
interrupt ID mapping, single-use handles, and state reset across requests.

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
| M3 | MCP server/client, tool schemas, authorization matrix, contract tests | Complete |
| M4 | Typed state, parallel routing, general node, specialist skeletons | Complete |
| M5 | Specialist workflows, entity resolution, tool-result verification | Complete |
| M6 | Policy engine and human-in-the-loop approval | Complete |
| M7 | Redis buffering and checkpoint persistence | Complete |
| M8 | Agent evals, tracing, structured logs, and metrics | Complete |
| M9 | Deployment and portfolio packaging | Planned |

## Current limitations and non-goals

- Debounce aggregation currently supports text; media preprocessing remains outside M7.
- Redis durability uses one instance with AOF. High-availability failover, automatic
  retention, and cross-store exactly-once execution are not implemented.
- Evaluation uses a finite synthetic corpus; replay results do not prove live model quality.
- Traces deliberately hide inputs/outputs. Prometheus metrics are local to each process;
  multi-process collection and production telemetry operations remain deployment concerns.
- Cost is unknown without token usage and explicitly configured model prices.
- Interrupted possible writes require inspection. Recovery does not automatically
  replay write nodes, and separate approved tools do not share a rollback boundary.
- The MVP deliberately excludes a frontend, mobile app, WhatsApp, Kafka,
  Kubernetes, RAG, and integrations with real business systems.

## Project documentation

- [Authoritative specification](docs/specs/COMMERCEOPS_AI_SPEC.md)
- [Target architecture](docs/architecture.md)
- [Development guide](docs/development.md)
- [Evaluation plan](docs/evaluation.md)
- [Operations notes](docs/operations.md)
- [M7 manual test guide](docs/m7-manual-test.md)
- [M8 manual test guide](docs/m8-manual-test.md)
- [M8 validation report](docs/reports/m8-validation.md)
- [Architecture decisions](docs/decisions/)

This repository is a sanitized implementation. It must contain only synthetic
data and generic prompts—never real client data, credentials, private endpoints,
or client-specific workflow logic.
