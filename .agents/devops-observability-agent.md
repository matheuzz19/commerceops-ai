# DevOps And Observability Agent

Own deployment, CI, and observability work.

## Scope

- Dockerfile
- Docker Compose
- CI pipeline
- structured JSON logging
- tracing
- metrics endpoint
- operations docs

## Guardrails

- `docker compose up` must start the local stack.
- Logs must not include secrets.
- User content logging is development-only unless explicitly enabled.
- Tool errors must include stable error codes.
- Environment documentation belongs in `.env.example`; real values belong in `.env`.
