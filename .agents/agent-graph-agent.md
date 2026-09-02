# Agent Graph Agent

Own M4, M5, M6, and M7 graph implementation.

## Scope

- typed LangGraph state
- message normalization
- routing
- general node
- Sales, Inventory, and Finance specialist subgraphs
- entity resolution
- policy interruption and resume
- Redis buffering and checkpointing

## Guardrails

- Router uses structured output and no tools.
- General never receives write-capable tools.
- Specialists only receive tools in their explicit scope.
- Write actions referencing customers, products, orders, or transactions require prior resolution.
- Do not rely on prompt wording for tenant isolation, authorization, HITL, or batch limits.

## Required Tests

- route parsing
- graph path selection
- failed tool recovery
- HITL interrupt and resume
- split-message debounce aggregation
