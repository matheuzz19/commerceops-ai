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

Specialist write execution now follows this enforced topology:

```text
Resolve trusted entities
      |
      v
Build ProposedAction
      |
      v
Policy: scope + schema + provenance + batch + risk
      |
      +-- denied ------> recoverable policy response
      +-- high risk ---> LangGraph interrupt
      |                       |
      |                 approve / reject
      |                       |
      +-- allowed <-----------+
      |
      v
Authorized MCP call
      |
      v
Verified tool result
```

The API owns checkpoint identity and binds each pending checkpoint to the
trusted tenant and user headers. A different tenant cannot approve or reject
the action. M6 uses LangGraph's in-memory checkpointer; Redis durability is an
explicit M7 responsibility.

Approval state is not added to tool arguments. For the one domain override
that must cross the MCP boundary—approved negative inventory—the resumed graph
creates a trusted `ToolRuntimeContext` grant. The executor passes that grant to
the deterministic service while continuing to reject tenant identity or other
trust data from model-controlled arguments.
