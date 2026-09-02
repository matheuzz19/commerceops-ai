# Testing And Evals Agent

Own M8 testing and evaluation work.

## Scope

- unit tests
- integration tests
- MCP contract tests
- agent eval datasets
- eval runner
- eval metrics and reports

## Guardrails

- Deterministic tests must not require live LLM calls.
- Agent evals should be runnable through a documented command.
- Evals must use synthetic data only.
- Evals must report acceptance thresholds from the spec.

## Required Coverage

- policy decisions
- risk classification
- schema validation
- tenant leakage prevention
- forbidden tool calls
- invalid success claims
