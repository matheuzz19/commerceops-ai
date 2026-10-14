# Architecture

CommerceOps AI follows the architecture defined in `docs/specs/COMMERCEOPS_AI_SPEC.md`.

```text
Client / API User
      |
      v
FastAPI API
      |
      v
Message Gateway
      |
      +--> Redis Conversation Buffer
      |
      v
NormalizedMessage
      |
      v
LangGraph Supervisor
      |
      +-- Send --> General Node -------+
      +-- Send --> Sales Subgraph -----+--> Result Aggregation
      +-- Send --> Inventory Subgraph -+
      +-- Send --> Finance Subgraph ---+
      |
      v
Policy Engine
      |
      v
MCP Client
      |
      v
CommerceOps MCP Server
      |
      v
Service Layer
      |
      v
PostgreSQL
```

## Services

- `agent-api`: FastAPI entrypoint and LangGraph execution
- `mcp-server`: MCP tools backed by application services
- `postgres`: business data, audit logs, and evaluation fixtures
- `redis`: message buffering and checkpoint support

## Trust Boundaries

- API headers resolve trusted `tenant_id` and `user_id` in local development.
- Agent/tool arguments must never supply `tenant_id`.
- Repository methods must require `tenant_id` and filter every query by it.

## M4 Routing Core

The supervisor uses structured classification to decompose one request into a
bounded set of department tasks. LangGraph `Send` dispatches those tasks in
parallel. Specialist results use a list reducer and are sorted back into router
order before the final response is composed. The router itself has no tools,
and General is the exclusive route for ambiguous or unsupported requests.

## M5 Specialist Execution

Each operational specialist follows a plan-resolve-execute-verify pipeline:

```text
Structured specialist plan
      |
      v
Resolve customer/product/order when required
      |
      v
Call one authorized MCP tool
      |
      v
Validate the tool-specific result schema
      |
      v
Compose a success, clarification, or recoverable failure response
```

Model output never supplies a trusted write identifier. Sales resolves customers
and products before creating orders and observes an order through `list_orders`
before a safe update. Inventory resolves products before stock operations.
Finance writes are limited to unlinked expenses in the current planner.

Parallel MCP branches use independent SQLAlchemy sessions. Their tool results
and resolved entities are reducer-backed state collections, preserving every
branch without sharing non-thread-safe database sessions.

## M6 Policy and HITL

Specialists prepare resolved write proposals in parallel. The supervisor waits
for all preparations, checks the total write count across departments, and
saves the policy decision and confirmation payload before entering review:

```text
Parallel specialist planning and entity resolution
      |
      v
Checkpoint PreparedWrite proposals (no business writes)
      |
      v
Evaluate scope, schema, provenance, total batch size, and risk
      |
      v
Checkpoint policy decision and complete review payload
      |
      v
Review: interrupt for approval when required
      |
      +-- rejected / denied --> verified non-execution response
      |
      v
Execute captured arguments through authorized MCP clients
      |
      v
Verify tool results and aggregate in original task order
```

Only the review node restarts on approval. It does not call the model, repeat
entity lookup, or replace the reviewed arguments. A high-risk action pauses
all proposed writes for that request, including lower-risk writes in another
department. The review payload lists every action that the decision covers.

The API owns checkpoint identity and binds each pending checkpoint to the
trusted tenant and user headers. A different tenant cannot approve or reject
the action. M6 uses LangGraph's in-memory checkpointer; Redis durability is an
explicit M7 responsibility.

Approval state is not added to tool arguments. For the one domain override
that must cross the MCP boundary—approved negative inventory—the resumed graph
creates a trusted `ToolRuntimeContext` grant. The executor passes that grant to
the deterministic service while continuing to reject tenant identity or other
trust data from model-controlled arguments.

Approval handles are consumed atomically before resume. Duplicate or competing
approval/rejection requests cannot execute the same pending action twice within
the M6 runtime. Each interrupt has an explicit ID; when multiple interrupts are
pending, the API exposes all payloads and resumes using an ID-to-decision map.
A subsequent interrupt gets a new approval handle, so an old request cannot
approve a newly surfaced action.

Per-request reducer collections are reset using LangGraph Overwrite when a new
message starts on an existing thread. This preserves append reducers during
parallel execution without mixing results from different requests.

M6 uses in-process checkpoints and approval claims. This is not a distributed
exactly-once guarantee. Durable claims and restart recovery remain M7 work.
After an uncertain resume failure, the API consumes the handle and returns a
safe failure instead of automatically replaying a possible business write.
Execution of multiple approved tools uses separate service transactions; a
later execution failure does not roll back earlier successful tools.

## M7 Buffering and Durable Sessions

The API resolves a tenant/session key using an unambiguous hash and binds the
session to the trusted user. Every message has a persistent receipt so retries
cannot duplicate the same execution. Text fragments share a debounced buffer;
a due-session index lets a lifespan worker recover queued work after restart.
An immediate message also flushes earlier buffered fragments for that session.

Redis execution leases serialize submissions and approvals across API workers.
Leases renew during long graph runs. Token-checked Lua updates fence stale
owners from overwriting metadata or receipts. Approval handles are still
consumed atomically and matched to the currently displayed session confirmation.

The LangGraph saver persists typed checkpoints, parent links, and pending writes
using plain Redis hashes and sorted sets. It uses an explicit project-type
serializer allowlist with no pickle fallback. One tenant/session thread is reused
across requests; M6 per-request reducer resets prevent old results leaking into
new responses. Normalized messages preserve all source message IDs.

GET session state reads the persisted checkpoint without initializing a model.
A restarted worker recovers saved completed outcomes and pending interrupts.
Unfinished possible writes are reported as interrupted and require inspection;
write nodes are never automatically replayed. Redis AOF and a named volume
provide single-instance durability, not high-availability failover or a shared
transaction with PostgreSQL.

## M8 evaluation and observation boundary

The evaluation harness runs the production graph and typed MCP adapter against
rollback-only synthetic PostgreSQL fixtures. Replay injects frozen model decisions;
live uses the configured classifier/planners. References only grade observed tools,
entity provenance, effects and safety; they never supply the executed actions.

Request observations wrap graph execution, including worker flushes and approval
resumes. LangChain callbacks collect node paths and available model usage. Verified
tool calls record validated outcome/latency. Request IDs correlate HTTP responses,
application events and LangSmith roots; buffered processing retains its intake ID.

LangSmith export hides all nested IO and strips exception text/model configuration.
JSON logs allow only safe event fields. Prometheus collectors use bounded route,
status and tool labels without tenant/session identity. Metrics are process-local;
external collection and deployment topology remain M9 concerns.

See ADR 0008 for the decisions and limits, and docs/evaluation.md for gates.
