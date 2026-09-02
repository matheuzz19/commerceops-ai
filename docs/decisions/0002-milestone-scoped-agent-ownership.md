# 0002 Milestone-Scoped Agent Ownership

## Status

Accepted

## Context

CommerceOps AI has several specialized implementation areas: deterministic backend code, MCP tooling, LangGraph workflows, evaluations, and deployment/observability. Mixing those concerns makes it easier for coding agents to skip required safety checks or implement milestones out of order.

## Decision

Create role-specific files under `.agents/` and use `AGENTS.md` as the shared instruction entrypoint.

## Consequences

- Future agents can start from a narrower scope.
- Reviews can check milestone-specific responsibilities.
- The project still uses one source of truth: the product and architecture spec.
