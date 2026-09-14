# ADR 0003: Send-Based Multi-Specialist Routing

## Status

Accepted

## Context

A single CommerceOps request can contain independent tasks for Sales, Inventory,
and Finance. Routing only to one primary department would require unnecessary
clarification or silently omit valid parts of the request.

## Decision

The supervisor uses a structured LangChain classifier to produce a bounded list
of department-scoped tasks. A LangGraph conditional edge converts those tasks
to `Send` objects, invoking the relevant specialist workers in parallel. The
router has no tools. Parallel results are combined through a reducer and sorted
by their original task positions before finalization.

General is an exclusive route: if clarification or unsupported behavior is
identified, action-capable specialists are not dispatched in the same plan.

## Consequences

- Multi-domain reads and, in later milestones, independent actions can be
  processed concurrently.
- Graph state must use reducer-backed result collections.
- Routing quality is evaluated using exact specialist-set matching.
- Specialist failures must be represented as structured partial results.
- Later policy work must evaluate every proposed action across every branch
  before execution or approval.
