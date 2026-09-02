# CommerceOps AI - Spec-Driven Development Document

## 1. Purpose

CommerceOps AI is a production-oriented multi-agent business operations platform built with Python, LangGraph, MCP, FastAPI, PostgreSQL and Redis.

The system receives natural-language business requests, normalizes the input, routes the request to the correct operational specialist, executes authorized tools through MCP, persists state and business data, evaluates agent behavior, traces execution, and supports human approval for risky actions.

This document is the source of truth for implementation. A coding agent must implement the system according to this spec and must not import any client-specific data, credentials, endpoints, prompts, identifiers, phone numbers, payloads, or branding from the architectural reference.

## 2. Sanitization Rules

The attached n8n workflow is only an architectural reference. It may inform high-level patterns:

- message intake and normalization
- multimodal preprocessing
- Redis-based buffering
- router-to-specialist delegation
- specialist tool isolation
- MCP tool usage
- PostgreSQL persistence
- operational guardrails
- logs and traceability

It must not be copied directly.

Forbidden material:

- original customer identity, business name, brand, contacts or domain-specific vocabulary
- credentials, API keys, tokens, webhook URLs, MCP URLs, database URLs or provider endpoints
- raw prompts from the original workflow
- real customer, product, transaction, order or inventory data
- node names, comments, sticky notes or labels that reveal the original implementation context
- WhatsApp-specific logic, Evolution API payloads or phone-number authorization rules

Decision: reimplement the architecture as a clean Python system, not as a migration of the n8n workflow.

Reason: the portfolio project must demonstrate engineering ability while avoiding leakage of client IP or operational secrets.

Rejected alternative: exporting the workflow, redacting secrets and publishing a near-identical version.

Consequence: more implementation work, but the resulting project is legally safer, more general and more defensible in interviews.

## 3. Product Requirements

### 3.1 MVP Scope

The MVP must support four operational areas:

| Area | Responsibility |
|---|---|
| Sales | customers, products and orders |
| Inventory | stock levels and inventory movements |
| Finance | revenue, expenses and financial summaries |
| General | greetings, help, clarification and out-of-scope responses |

The system must support these end-to-end workflows:

1. Create an order for an existing customer and existing products.
2. List a customer's orders.
3. Create a customer.
4. Search customers.
5. Search products.
6. Check inventory level for a product.
7. Create an inventory movement.
8. List inventory movements.
9. Get monthly financial summary.
10. List transactions.
11. Record an expense.
12. Respond to general help or clarification requests without tools.

### 3.2 Non-Goals

The MVP must not include:

- WhatsApp integration
- Evolution API
- full frontend
- mobile app
- Kubernetes
- Kafka
- vector database
- RAG
- multiple LLM providers
- voice responses
- complex production authentication
- recipe management
- supplier management
- advanced analytics
- direct integration with real external business systems

Decision: the first release prioritizes agent architecture, tool safety, testing, deployment and observability.

Reason: these prove the ADLC story: build, test, deploy and monitor.

Rejected alternative: adding many integrations to make the project look larger.

Consequence: the MVP stays focused and can reach production-like quality faster.

## 4. System Architecture

Target architecture:

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
      +--> General Node
      +--> Sales Subgraph
      +--> Inventory Subgraph
      +--> Finance Subgraph
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

Required deployable services:

- `agent-api`: FastAPI entrypoint and LangGraph execution
- `mcp-server`: MCP tools backed by application services
- `postgres`: business data, audit logs and evaluation fixtures
- `redis`: conversation buffering and checkpoint support

Decision: use one MCP server with tool-level authorization for the MVP.

Reason: it demonstrates least privilege without multiplying deployment complexity.

Rejected alternative: separate MCP servers for Sales, Inventory and Finance in v1.

Consequence: simpler local development and deployment, while still enforcing specialist scopes in code.

## 5. Repository Structure

The implementation should use this structure:

```text
commerceops-ai/
  src/commerceops/
    api/
      main.py
      routes/
      schemas/
      dependencies.py
    agents/
      supervisor/
      sales/
      inventory/
      finance/
      general.py
    graph/
      state.py
      routing.py
      policy.py
      checkpoints.py
    mcp/
      server.py
      client.py
      tools/
    domain/
      models.py
      enums.py
      invariants.py
    services/
      customers.py
      products.py
      orders.py
      inventory.py
      finance.py
    repositories/
    db/
      session.py
      migrations/
      seed.py
    evals/
      runner.py
      metrics.py
    observability/
      tracing.py
      logging.py
      metrics.py
    config.py
  tests/
    unit/
    integration/
    contract/
    evals/
  evals/
    datasets/
  docs/
    decisions/
    architecture.md
    evaluation.md
    operations.md
  docker-compose.yml
  Dockerfile
  pyproject.toml
  .env.example
  README.md
```

## 6. Domain Model

All business entities except `Tenant` must include `tenant_id`.

### 6.1 Entities

```text
Tenant
  id
  name
  created_at

User
  id
  tenant_id
  email
  role
  created_at

Customer
  id
  tenant_id
  name
  email
  phone
  created_at

Product
  id
  tenant_id
  name
  sku
  price
  active
  created_at

Order
  id
  tenant_id
  customer_id
  status
  payment_status
  total_amount
  created_at

OrderItem
  id
  tenant_id
  order_id
  product_id
  quantity
  unit_price

InventoryMovement
  id
  tenant_id
  product_id
  movement_type
  quantity
  reason
  created_at

Transaction
  id
  tenant_id
  order_id nullable
  type
  status
  amount
  description
  created_at
```

### 6.2 Enums

```text
OrderStatus: DRAFT, CONFIRMED, CANCELLED, FULFILLED
PaymentStatus: UNPAID, PAID, REFUNDED
InventoryMovementType: IN, OUT, ADJUSTMENT
TransactionType: REVENUE, EXPENSE
TransactionStatus: PENDING, POSTED, CANCELLED
UserRole: ADMIN, OPERATOR, VIEWER
```

### 6.3 Inventory Ledger

Inventory must be represented as a ledger of `InventoryMovement` rows.

Current stock is computed as:

```text
SUM(IN) - SUM(OUT) + SUM(ADJUSTMENT)
```

`ADJUSTMENT` quantity may be positive or negative.

Decision: use a ledger rather than a single mutable `current_quantity` field.

Reason: a ledger preserves operational history and supports auditability.

Rejected alternative: store current stock only.

Consequence: inventory reads require aggregation, which is acceptable for the MVP dataset.

## 7. System Invariants

These rules must be enforced in code, not only in prompts:

1. No business query may read rows outside the current `tenant_id`.
2. No business write may create rows outside the current `tenant_id`.
3. The LLM must never provide trusted database IDs directly to write tools unless those IDs came from prior tool results in the same graph execution or persisted conversation context.
4. Write operations that reference customers or products must pass through entity resolution first.
5. Tool inputs must be validated with Pydantic schemas before execution.
6. Tool outputs must be structured and validated before being added to graph state.
7. Specialists may call only tools explicitly granted by their scope.
8. `MAX_BATCH_WRITE = 5`.
9. More than five proposed writes must trigger HITL instead of partial execution.
10. High-risk actions must trigger HITL before execution.
11. The assistant must not claim a write succeeded until the tool result confirms success.
12. Failed tool calls must produce a recoverable graph state and a user-safe explanation.
13. General requests must not receive write-capable tools.

## 8. MCP Tool Contracts

Every MCP tool must accept `tenant_id` from trusted runtime context, not from the LLM.

Every tool result must include:

```json
{
  "ok": true,
  "data": {},
  "error": null,
  "audit_id": "string"
}
```

On failure:

```json
{
  "ok": false,
  "data": null,
  "error": {
    "code": "string",
    "message": "safe user-facing message"
  },
  "audit_id": "string"
}
```

### 8.1 Sales Tools

#### `search_customers`

Input:

```json
{
  "query": "string",
  "limit": 10
}
```

Output data:

```json
{
  "customers": [
    {
      "id": "string",
      "name": "string",
      "email": "string | null",
      "phone": "string | null"
    }
  ]
}
```

#### `create_customer`

Input:

```json
{
  "name": "string",
  "email": "string | null",
  "phone": "string | null"
}
```

#### `search_products`

Input:

```json
{
  "query": "string",
  "active_only": true,
  "limit": 10
}
```

#### `list_orders`

Input:

```json
{
  "customer_id": "string | null",
  "status": "string | null",
  "limit": 20
}
```

#### `create_order`

Input:

```json
{
  "customer_id": "string",
  "items": [
    {
      "product_id": "string",
      "quantity": 1
    }
  ]
}
```

Requirements:

- customer must belong to current tenant
- each product must belong to current tenant
- each product must be active
- quantity must be positive
- total must be computed server-side
- order creation should also create a pending revenue transaction only if the product/order policy says so; otherwise financial posting remains explicit

#### `update_order`

Input:

```json
{
  "order_id": "string",
  "status": "CONFIRMED | CANCELLED | FULFILLED",
  "payment_status": "UNPAID | PAID | REFUNDED | null"
}
```

### 8.2 Inventory Tools

#### `get_inventory_level`

Input:

```json
{
  "product_id": "string"
}
```

Output data:

```json
{
  "product_id": "string",
  "available_quantity": 0
}
```

#### `list_inventory_movements`

Input:

```json
{
  "product_id": "string | null",
  "limit": 20
}
```

#### `create_inventory_movement`

Input:

```json
{
  "product_id": "string",
  "movement_type": "IN | OUT | ADJUSTMENT",
  "quantity": 1,
  "reason": "string"
}
```

Requirements:

- product must belong to current tenant
- `IN` and `OUT` quantities must be positive
- `OUT` must not make stock negative unless explicitly approved by HITL
- large adjustments require HITL

### 8.3 Finance Tools

#### `get_financial_summary`

Input:

```json
{
  "period_start": "YYYY-MM-DD",
  "period_end": "YYYY-MM-DD"
}
```

Output data:

```json
{
  "revenue": 0,
  "expenses": 0,
  "net": 0,
  "transaction_count": 0
}
```

#### `list_transactions`

Input:

```json
{
  "type": "REVENUE | EXPENSE | null",
  "status": "PENDING | POSTED | CANCELLED | null",
  "limit": 20
}
```

#### `create_transaction`

Input:

```json
{
  "type": "REVENUE | EXPENSE",
  "amount": 0,
  "description": "string",
  "order_id": "string | null"
}
```

Requirements:

- amount must be positive
- large transactions require HITL
- linked order must belong to current tenant

## 9. Tool Authorization Matrix

| Tool | Sales | Inventory | Finance | General |
|---|---:|---:|---:|---:|
| search_customers | yes | no | no | no |
| create_customer | yes | no | no | no |
| search_products | yes | yes | no | no |
| list_orders | yes | no | no | no |
| create_order | yes | no | no | no |
| update_order | yes | no | no | no |
| get_inventory_level | no | yes | no | no |
| list_inventory_movements | no | yes | no | no |
| create_inventory_movement | no | yes | no | no |
| get_financial_summary | no | no | yes | no |
| list_transactions | no | no | yes | no |
| create_transaction | no | no | yes | no |

Decision: Finance does not receive `list_orders` in the MVP.

Reason: Finance should operate on transactions and summaries, reducing coupling with Sales.

Rejected alternative: allow Finance read-only access to orders.

Consequence: financial questions involving orders must be answered through transactions unless future requirements justify cross-domain access.

## 10. LangGraph State

The graph state must be explicit and typed.

```python
class NormalizedMessage(BaseModel):
    tenant_id: str
    user_id: str
    session_id: str
    message_id: str
    content: str
    content_type: Literal["text", "audio", "image", "document"]
    timestamp: datetime

class RouteDecision(BaseModel):
    department: Literal["sales", "inventory", "finance", "general"]
    confidence: float
    reason: str

class ResolvedEntity(BaseModel):
    entity_type: Literal["customer", "product", "order", "transaction"]
    id: str
    display_name: str
    source_tool_call_id: str

class ProposedAction(BaseModel):
    tool_name: str
    arguments: dict[str, Any]
    risk_level: Literal["low", "medium", "high"]
    requires_confirmation: bool

class AgentState(TypedDict):
    messages: list
    normalized_message: NormalizedMessage
    route: RouteDecision | None
    tenant_id: str
    user_id: str
    session_id: str
    intent: str | None
    resolved_entities: list[ResolvedEntity]
    proposed_actions: list[ProposedAction]
    tool_results: list[dict]
    requires_confirmation: bool
    confirmation_request: dict | None
    error: str | None
    final_response: str | None
```

## 11. LangGraph Flow

### 11.1 Supervisor Graph

```text
START
  |
  v
normalize_message
  |
  v
route_request
  |
  +--> sales_subgraph
  +--> inventory_subgraph
  +--> finance_subgraph
  +--> general_response
  |
  v
finalize_response
  |
  v
END
```

Router requirements:

- use structured output
- return only one department
- include confidence and reason
- route ambiguous action requests to `general`
- route multi-domain requests to the primary domain in MVP and ask clarifying questions when execution would require multiple specialists

Decision: router is a structured LLM node, not a full agent.

Reason: it classifies intent and should not use tools.

Rejected alternative: agent executor router with tool access.

Consequence: routing becomes easier to evaluate and less error-prone.

### 11.2 Sales Subgraph

```text
understand_sales_request
  |
  v
resolve_customer_if_needed
  |
  v
resolve_products_if_needed
  |
  v
validate_sales_action
  |
  v
policy_check
  |
  +--> request_confirmation
  +--> execute_sales_tool
  |
  v
verify_tool_result
  |
  v
respond
```

Sales invariants:

- creating orders requires resolved customer and resolved products
- listing orders by natural-language customer name requires customer lookup first
- never invent customer or product IDs

### 11.3 Inventory Subgraph

```text
understand_inventory_request
  |
  v
resolve_product_if_needed
  |
  v
validate_inventory_action
  |
  v
policy_check
  |
  +--> request_confirmation
  +--> execute_inventory_tool
  |
  v
verify_tool_result
  |
  v
respond
```

Inventory invariants:

- all stock actions require resolved product
- negative stock requires HITL
- large adjustments require HITL

### 11.4 Finance Subgraph

```text
understand_finance_request
  |
  v
normalize_period_or_amount
  |
  v
validate_finance_action
  |
  v
policy_check
  |
  +--> request_confirmation
  +--> execute_finance_tool
  |
  v
verify_tool_result
  |
  v
respond
```

Finance invariants:

- date ranges must be explicit or derived deterministically from current tenant timezone
- transaction amounts must be positive
- large transactions require HITL

### 11.5 General Node

General must answer without tools.

It handles:

- greetings
- help
- clarification
- unsupported requests
- ambiguous requests
- requests outside MVP scope

Decision: General is not a specialist agent.

Reason: General does not perform business actions.

Rejected alternative: give General its own full tool-capable agent.

Consequence: lower complexity and smaller attack surface.

## 12. Policy and Human-in-the-Loop

### 12.1 Risk Classification

Low risk:

- search
- list
- summaries
- inventory lookup

Medium risk:

- create customer
- create normal order
- small inventory movement
- small expense

High risk:

- order cancellation
- refund-like state change
- inventory movement that would make stock negative
- inventory adjustment above threshold
- financial transaction above threshold
- more than five writes
- bulk write

Initial thresholds:

```text
MAX_BATCH_WRITE = 5
LARGE_INVENTORY_MOVEMENT = 100
LARGE_TRANSACTION_AMOUNT = 1000.00
```

### 12.2 Policy Engine

The policy engine must evaluate:

- tool scope
- tenant context
- schema validity
- entity resolution requirements
- batch size
- risk level
- confirmation requirement

Policy result:

```python
class PolicyDecision(BaseModel):
    allowed: bool
    requires_confirmation: bool
    reason: str
    violations: list[str]
```

If `requires_confirmation = true`, LangGraph must interrupt execution and return a confirmation payload.

Confirmation payload:

```json
{
  "message": "Please approve this action.",
  "action": {
    "tool_name": "string",
    "arguments": {}
  },
  "risk_reason": "string"
}
```

Decision: high-risk actions pause through HITL instead of relying on cautious wording.

Reason: approval is a runtime control, not a prompt preference.

Rejected alternative: instruct the LLM to ask before risky operations.

Consequence: the graph must support checkpointing and resume.

## 13. Multi-Tenancy

Tenant isolation is mandatory.

Requirements:

- every API request must resolve `tenant_id` from trusted auth or dev-mode header
- no MCP tool may accept `tenant_id` from model-generated arguments
- every repository method must require `tenant_id`
- every SQL query must filter by `tenant_id`
- tests must prove cross-tenant reads and writes are rejected

For MVP local development, use a simple header:

```text
X-Tenant-ID
X-User-ID
```

Production auth is a non-goal, but the code must isolate the trust boundary so real auth can replace the dev header later.

Decision: use generic SaaS tenant isolation instead of phone-number identity.

Reason: tenant isolation is broadly relevant and avoids copying original channel-specific logic.

Rejected alternative: reuse phone-based identity.

Consequence: the portfolio communicates a reusable business architecture.

## 14. Message Handling and Buffering

The message gateway must support debounced aggregation.

Example:

```text
Message 1: "Create an order"
Message 2: "for Alice"
Message 3: "two wireless keyboards"
Expected: one agent execution after debounce window
```

Requirements:

- store incoming messages in Redis by `tenant_id + session_id`
- use a configurable debounce window
- aggregate buffered text into one `NormalizedMessage`
- preserve source message IDs for audit
- support immediate execution for API calls that set `debounce=false`

Initial setting:

```text
MESSAGE_DEBOUNCE_SECONDS = 3
```

Decision: preserve the buffering pattern from the architectural reference.

Reason: business chat users often split one intent across multiple short messages.

Rejected alternative: execute the agent once per incoming message.

Consequence: better UX and fewer partial tool calls, with additional Redis complexity.

## 15. API Requirements

Required endpoints:

```text
GET /health
POST /messages
POST /confirmations/{checkpoint_id}/approve
POST /confirmations/{checkpoint_id}/reject
GET /sessions/{session_id}/state
GET /metrics
```

`POST /messages` input:

```json
{
  "session_id": "string",
  "message_id": "string",
  "content": "string",
  "content_type": "text",
  "debounce": false
}
```

`POST /messages` output:

```json
{
  "status": "completed | buffered | requires_confirmation | failed",
  "response": "string | null",
  "checkpoint_id": "string | null",
  "trace_id": "string"
}
```

## 16. Testing Requirements

### 16.1 Unit Tests

Must cover:

- domain invariants
- inventory ledger calculations
- policy decisions
- risk classification
- schema validation
- tenant-scoped repositories
- route parsing
- message aggregation

### 16.2 Integration Tests

Must cover:

- FastAPI to LangGraph execution
- LangGraph to MCP tools
- MCP tools to PostgreSQL
- Redis buffering
- HITL interrupt and resume
- failed tool recovery

### 16.3 Contract Tests

Every MCP tool must have contract tests for:

- valid input
- invalid input
- unauthorized specialist
- cross-tenant access attempt
- structured success response
- structured failure response

### 16.4 Agent Evals

Create evaluation datasets:

```text
evals/datasets/routing.jsonl
evals/datasets/tool_selection.jsonl
evals/datasets/entity_resolution.jsonl
evals/datasets/task_completion.jsonl
evals/datasets/policy_violations.jsonl
```

Minimum MVP dataset:

- 40 routing cases
- 30 tool-selection cases
- 20 entity-resolution cases
- 20 task-completion cases
- 20 policy/safety cases

Metrics:

```text
routing_accuracy
tool_selection_accuracy
entity_resolution_accuracy
task_completion_rate
forbidden_tool_call_rate
tenant_leakage_rate
hitl_trigger_accuracy
invalid_success_claim_rate
p50_latency
p95_latency
average_cost_per_request
```

Initial acceptance thresholds:

```text
routing_accuracy >= 0.90
forbidden_tool_call_rate == 0
tenant_leakage_rate == 0
invalid_success_claim_rate == 0
task_completion_rate >= 0.80
```

Decision: evals are part of the MVP, not final polish.

Reason: an AI Engineer portfolio must prove quality quantitatively.

Rejected alternative: rely on a few manual demos.

Consequence: CI must be able to run deterministic software tests and agent evals separately.

## 17. Observability

Every request must produce a trace containing:

- request ID
- tenant ID
- session ID
- route decision
- graph path
- tool calls
- policy decisions
- HITL events
- tool latency
- LLM latency
- total latency
- token usage when available
- cost estimate when available
- final status

Logging rules:

- logs must be structured JSON
- logs must not include credentials
- logs must not include raw secrets
- user content may be logged only in development unless explicitly enabled
- tool errors must include stable error codes

Recommended integrations:

- LangSmith for graph/LLM traces
- OpenTelemetry-compatible instrumentation
- Prometheus-style `/metrics` endpoint

## 18. Deployment

Local deployment must work with:

```text
docker compose up
```

Required containers:

- FastAPI app
- MCP server
- PostgreSQL
- Redis

Required environment variables in `.env.example`:

```text
OPENAI_API_KEY=
DATABASE_URL=
REDIS_URL=
LANGSMITH_API_KEY=
LANGSMITH_TRACING=
MESSAGE_DEBOUNCE_SECONDS=
MAX_BATCH_WRITE=
LARGE_INVENTORY_MOVEMENT=
LARGE_TRANSACTION_AMOUNT=
```

`.env.example` must not contain real secrets.

CI pipeline:

```text
lint
typecheck
unit tests
integration tests
MCP contract tests
agent evals
docker build
```

## 19. Acceptance Criteria

The MVP is acceptable only when all criteria are true:

1. `docker compose up` starts the stack successfully.
2. Database migrations run from a clean database.
3. Seed data is synthetic and multi-tenant.
4. `POST /messages` can complete Sales, Inventory and Finance workflows.
5. General requests do not call tools.
6. Sales cannot call Inventory-only or Finance-only tools.
7. Inventory cannot call Sales-only or Finance-only tools.
8. Finance cannot call Sales-only or Inventory-only tools.
9. Cross-tenant access is blocked in tests.
10. The agent resolves customer/product names before write actions.
11. More than five writes triggers HITL.
12. High-risk actions trigger HITL.
13. Tool failure does not produce a false success response.
14. Evals run through a documented command.
15. Required eval thresholds pass.
16. Traces show router, specialist, policy and tool execution steps.
17. README explains architecture, trade-offs, evals, deployment and limitations.
18. No original client data, credentials, endpoints, prompts or identity appears in the repository.

## 20. Milestones

### M0 — Specification and Sanitization

Deliverables:

- this spec
- explicit non-goals
- sanitized architecture description
- initial ADRs

Done when:

- implementation agent can start without asking architectural questions
- no original sensitive data is present

### M1 — Foundation

Deliverables:

- Python project skeleton
- FastAPI health endpoint
- config management
- lint, typecheck and pytest setup
- Docker Compose with PostgreSQL and Redis

Done when:

- app boots locally
- CI-compatible checks pass

### M2 — Domain and Backend

Deliverables:

- SQLAlchemy models
- migrations
- repositories
- service layer
- synthetic seed data

Done when:

- deterministic service tests pass
- tenant isolation tests pass

### M3 — MCP Layer

Deliverables:

- CommerceOps MCP server
- all MVP tools
- tool schemas
- authorization matrix
- contract tests

Done when:

- tools work through MCP
- unauthorized tool access is rejected

### M4 — LangGraph Core

Deliverables:

- typed graph state
- normalized message handling
- router
- general node
- specialist subgraph skeletons

Done when:

- routing eval baseline passes
- requests reach correct graph path

### M5 — Specialist Workflows

Deliverables:

- Sales workflows
- Inventory workflows
- Finance workflows
- entity resolution
- tool result verification

Done when:

- core workflows pass integration tests
- no writes occur with invented IDs

### M6 — Policy and HITL

Deliverables:

- policy engine
- risk classification
- batch policy
- graph interrupts
- approval/rejection endpoints

Done when:

- high-risk actions pause
- approved actions resume
- rejected actions do not execute

### M7 — Buffering and Checkpointing

Deliverables:

- Redis message buffer
- debounce aggregation
- session state inspection
- checkpoint persistence

Done when:

- split-message workflow results in one agent execution

### M8 — Testing, Evals and Observability

Deliverables:

- eval datasets
- eval runner
- metric reports
- traces
- structured logs
- `/metrics`

Done when:

- acceptance thresholds pass
- traces are usable for debugging

### M9 — Deployment and Portfolio Packaging

Deliverables:

- production-like Docker setup
- README
- architecture diagram
- evaluation report
- limitations
- demo script

Done when:

- a recruiter or engineer can run and understand the project from the README

## 21. Definition of Done

The project is done when:

- all acceptance criteria pass
- all required tests and evals pass
- local deployment is reproducible
- observability is wired
- HITL is demonstrable
- tenant isolation is tested
- README includes architecture, decisions, metrics and limitations
- no sensitive original material is present
- every architectural decision has a clear reason and trade-off

## 22. Coding Agent Instructions

The coding agent must:

1. Treat this document as authoritative.
2. Implement milestones in order unless explicitly instructed otherwise.
3. Prefer deterministic backend behavior before agent behavior.
4. Encode safety-critical behavior in code, graph topology or policy checks.
5. Avoid relying on prompts for tenant isolation, authorization, batch limits or HITL.
6. Keep prompts short, generic and sanitized.
7. Add tests with every milestone.
8. Never copy raw content from the reference n8n workflow.
9. Never add real credentials or client-specific material.
10. Stop and report if implementation requires a decision not covered by this spec.
