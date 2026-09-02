# 0001 Spec-Driven Sanitized Reimplementation

## Status

Accepted

## Context

CommerceOps AI is a portfolio project derived from high-level architectural patterns. The project must avoid leaking client identity, credentials, prompts, endpoints, operational data, or implementation labels from any external reference.

## Decision

Use `docs/specs/COMMERCEOPS_AI_SPEC.md` as the source of truth and reimplement the system as a clean Python application.

## Consequences

- More implementation work is required.
- The repository remains safer to publish and easier to discuss in interviews.
- Coding agents must stop if they need a decision not covered by the spec.
