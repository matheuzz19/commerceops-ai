# ADR 0004: Plan, Resolve, Execute, Verify Specialist Pipeline

## Status

Accepted

## Context

Specialist models must understand natural-language operations without being
trusted to invent database identifiers, bypass tool scopes, or interpret an
unvalidated tool payload as success.

## Decision

Each M5 specialist uses a tool-free structured planner followed by deterministic
application code. The application validates required arguments, resolves every
referenced entity through an authorized read tool, executes the selected MCP
tool with trusted runtime identity, and validates the tool-specific output model
before composing a response.

Parallel specialists use independent database sessions. Resolved entities and
tool results use LangGraph reducers so concurrent branches cannot overwrite one
another.

High-risk actions are rejected until M6 provides runtime policy decisions and
checkpointed human approval.

## Consequences

- Models operate on names and natural-language references instead of trusted IDs.
- Missing or ambiguous entity matches stop writes and request clarification.
- A generic or malformed tool success cannot produce a success claim.
- Specialist planning remains easy to test through injected deterministic plans.
- Policy and HITL can be added after planning and before execution in M6.
