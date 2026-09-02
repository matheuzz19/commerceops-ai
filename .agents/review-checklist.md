# Review Checklist

Use this checklist before handing off or merging milestone work.

## Safety

- No secrets, credentials, provider endpoints, or client-specific data were added.
- Tenant isolation is enforced in code for all business reads and writes.
- Agent prompts are not relied on for authorization, tenant isolation, HITL, or batch limits.
- Tool outputs are checked before user-facing success claims.

## Architecture

- The change follows the spec milestone currently being implemented.
- New code fits the existing package boundaries.
- MCP tools use the standard response envelope.
- Specialist access matches the authorization matrix.

## Tests

- Unit tests cover deterministic business logic.
- Integration tests cover service boundaries touched by the change.
- Contract tests cover MCP inputs, authorization, and result envelopes.
- Evals are updated when routing, tool selection, entity resolution, or policy behavior changes.

## Operations

- Environment variables are documented in `.env.example`.
- Logs avoid secrets and use stable error codes where applicable.
- Docker/CI changes are documented in `docs/operations.md` or `docs/development.md`.
