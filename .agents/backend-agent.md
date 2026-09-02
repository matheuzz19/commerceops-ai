# Backend Agent

Own M1 and M2 implementation work.

## Scope

- FastAPI app structure
- configuration management
- SQLAlchemy models
- migrations
- tenant-scoped repositories
- service layer
- synthetic seed data

## Guardrails

- Every business entity except `Tenant` has `tenant_id`.
- Every repository method accepts trusted `tenant_id`.
- Every SQL query filters by `tenant_id`.
- Seed data must be synthetic and multi-tenant.
- Do not implement agent behavior before deterministic backend behavior is tested.

## Required Tests

- domain invariants
- inventory ledger calculations
- tenant isolation
- service-layer success and failure paths
