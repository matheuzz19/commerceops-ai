# ADR 0005: Checkpointed policy approval

## Status

Accepted for M6.

## Decision

Convert every specialist write into a typed proposed action after entity
resolution. Evaluate authorization, schema validity, entity provenance, batch
size, and deterministic risk in application code. High-risk actions pause with
a LangGraph interrupt and resume only through tenant-and-user-scoped API
approval or rejection.

M6 uses an in-process LangGraph checkpointer. Redis persistence remains M7 so
the milestone does not mix approval correctness with buffering and durability.

## Rationale

Approval is a runtime control, not a prompt instruction. Keeping trusted
identity and approval grants outside model-generated tool arguments prevents a
planner from granting itself permission or crossing tenant boundaries.

## Consequences

- A write cannot execute before policy evaluation.
- Rejection resumes the graph but performs no write.
- Approved negative stock uses a narrowly scoped trusted MCP runtime grant.
- Pending approvals do not survive an API process restart until M7.
