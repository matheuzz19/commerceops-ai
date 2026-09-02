# Evaluation

Agent evals are part of the MVP and must run separately from deterministic software tests.

Datasets live in `evals/datasets`:

- `routing.jsonl`
- `tool_selection.jsonl`
- `entity_resolution.jsonl`
- `task_completion.jsonl`
- `policy_violations.jsonl`

Required metrics:

- `routing_accuracy`
- `tool_selection_accuracy`
- `entity_resolution_accuracy`
- `task_completion_rate`
- `forbidden_tool_call_rate`
- `tenant_leakage_rate`
- `hitl_trigger_accuracy`
- `invalid_success_claim_rate`
- `p50_latency`
- `p95_latency`
- `average_cost_per_request`

Initial thresholds are defined in the spec.
