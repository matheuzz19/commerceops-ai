# ADR 0008: Evaluation evidence and private observability

## Status

Accepted for M8, subject to the documented release evaluation results.

## Decision

Keep reference datasets and frozen replay inputs separate. Replay executes the real
LangGraph, in-process MCP adapter, schemas, services and PostgreSQL, replacing only
model decisions. Live mode evaluates the configured router and specialist models.
Reports explicitly identify whether a model was tested and include dataset hashes,
SDK versions, per-case outcomes, latency, available token usage and configured costs.

Run each synthetic scenario in an outer PostgreSQL transaction. Tool commits release
savepoints; the harness rolls back the outer transaction. Only commerceops_test may
be used. A per-case lock protects the shared SQLAlchemy session in the harness;
production MCP tools continue to use independent sessions.

Verify tool trajectories, resolved IDs and audit provenance, tenant boundaries,
expected business effects, high-risk review, rejection, and success claims. Mandatory
spec thresholds, dataset sizes, execution errors and HITL correctness gate live
reports. Replay additionally requires every reference to pass. Missing cost information stays null, rather than being interpreted as zero.

Export LangSmith traces with correlated request/tenant/session IDs and safe execution
metadata. Hide inputs and outputs on all nested runs; strip exception text, serialized
model configuration and non-allowlisted metadata before export. Preserve graph paths,
policy decisions, tool outcomes, status, timings and available usage data.

Expose process-local Prometheus counters and histograms at /metrics. Labels use
route templates, fixed statuses and known tool names, never tenant/session IDs or
raw URLs. JSON application events use an explicit allowlist and omit user content.

## Rationale

Replay provides reproducible CI evidence for execution and safety contracts. It does
not prove model understanding. Live evaluation provides that separate evidence.
Typed references and database checks prevent a fluent answer from being scored as
a completed business operation without verified effects.

The evaluation uncovered SKU search that only matched names and a finance JSON
schema whose Decimal pattern prevented structured model output. SKU search now
includes the SKU while retaining tenant/active filters. Finance transports decimal
strings and still validates/calculates using Decimal in application code.

## Trade-offs

- The synthetic corpus covers MVP contracts, not production traffic distributions.
- Replay classification accuracy describes fixture execution, not model accuracy.
- Deterministic safety probes bypass the model to test enforcement directly.
- Hiding IO reduces exposure but removes prompt/response inspection from traces.
- Pricing is supplied explicitly; estimates do not include cached-token discounts,
  taxes or billing adjustments. Unknown rates produce no fabricated estimate.
- Histograms and counters are per process; multi-process deployments need a
  supported collector strategy. No telemetry collector service is added in M8.
- API ingress returns quickly for buffered messages; graph latency measures
  processing separately and does not include time waiting for debounce/HITL.
- Live evals run explicitly and consume provider tokens; normal CI uses replay.
