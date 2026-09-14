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
Finance M5 writes are limited to unlinked expenses. High-risk and combined
cross-specialist writes remain blocked pending M6 policy and HITL controls.

Parallel MCP branches use independent SQLAlchemy sessions. Their tool results
and resolved entities are reducer-backed state collections, preserving every
branch without sharing non-thread-safe database sessions.
