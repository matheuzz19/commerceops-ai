# MCP Agent

Own M3 implementation work.

## Scope

- CommerceOps MCP server
- MCP client adapter
- tool schemas
- tool authorization matrix
- structured tool results
- audit IDs

## Guardrails

- Tools accept `tenant_id` only from trusted runtime context.
- Tool arguments from the model must never include trusted IDs unless they came from prior tool results.
- All tool inputs and outputs are validated with Pydantic schemas.
- Tool results always use the standard `{ok, data, error, audit_id}` envelope.
- Unauthorized specialist access returns a structured failure.

## Required Tests

- valid input
- invalid input
- unauthorized specialist
- cross-tenant access attempts
- structured success envelope
- structured failure envelope
