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

## M4 Routing Baseline

`routing.jsonl` contains at least 40 sanitized single-domain, ambiguous, and
multi-domain cases. Routing correctness uses exact agent-set equality so both
missing and unnecessary specialist dispatches count as failures.

Run the live-model baseline with an explicitly configured API key:

```powershell
python -m commerceops.evals.routing evals/datasets/routing.jsonl
```

The command exits unsuccessfully when routing accuracy is below `0.90`. The
broader evaluation runner, latency/cost reporting, and remaining datasets are
implemented in M8.

Latest verified baseline (2026-09-14):

- Model: `gpt-5.4-mini`
- Dataset: 41 cases
- Exact agent-set accuracy: `1.00` (41/41)
- LangSmith project: `commerceops-ai-m4`
- Trace tags: `m4`, `routing-baseline`
