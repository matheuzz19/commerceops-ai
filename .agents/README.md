# Development Agents

These files divide the CommerceOps AI implementation by responsibility. All agents must follow `AGENTS.md` and `docs/specs/COMMERCEOPS_AI_SPEC.md`.

## Agents

- `backend-agent.md`: FastAPI foundation, database, repositories, services, seed data
- `mcp-agent.md`: MCP server, schemas, tool contracts, authorization
- `agent-graph-agent.md`: LangGraph state, routing, specialists, HITL, buffering
- `testing-evals-agent.md`: unit tests, integration tests, contract tests, eval datasets, metrics
- `devops-observability-agent.md`: Docker, CI, logging, tracing, metrics, operations docs

## Handoff Rules

- Record unresolved decisions in `docs/decisions`.
- Add tests in the same milestone as implementation.
- Keep tool and graph behavior aligned with the authorization matrix.
- Never add real client data or real secrets.
