# M8 manual verification

Use the existing [M7 manual guide](m7-manual-test.md) to start the stack, apply
migrations, seed synthetic data and configure model credentials locally.

## 1. Reproduce evaluation evidence

~~~powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://commerceops:commerceops@localhost:5433/commerceops_test"
python -m commerceops.evals.runner --mode replay --output evals/reports/replay.json
python -m commerceops.evals.runner --mode live --concurrency 4 --output evals/reports/live.json
Get-Content evals/reports/live.json
~~~

Check mode, model_tested, passed, checks and metrics. Replay does not measure the
model. Live must pass the release thresholds. Inspect failing case IDs before
changing implementation or dataset expectations.

## 2. Inspect metrics

Submit a synthetic inventory lookup and an expense through the M7 guide, then:

~~~powershell
(Invoke-WebRequest http://localhost:8000/metrics).Content
~~~

Expect commerceops_http_requests_total, commerceops_graph_runs_total,
commerceops_graph_duration_seconds_bucket, commerceops_tool_calls_total,
commerceops_llm_tokens_total and commerceops_hitl_events_total after corresponding
operations. Identity, credentials and message content must not appear as labels.

Suggested PromQL for graph p95 over five minutes:

~~~promql
histogram_quantile(0.95, sum(rate(commerceops_graph_duration_seconds_bucket[5m])) by (le))
~~~

Counters/histograms are local to each API process and reset on restart. Cost series
only accumulates when rates and usage are available. GET /metrics does not count
its own scrape as a business request.

## 3. Inspect logs and traces

~~~powershell
docker compose logs --tail 100 agent-api
~~~

Application events should be JSON with request_id, tenant_id and session_id for
execution, plus graph_node, route_decision, policy_decision, tool_result,
hitl_pause/hitl_decision and graph_finished as applicable. User content and raw
exception text are excluded.

Set LANGSMITH_TRACING=true, LANGSMITH_API_KEY and LANGSMITH_PROJECT locally. Open
the configured LangSmith project, find commerceops.request by the response trace_id,
and inspect graph/model/tool child runs. Inputs and outputs are hidden deliberately;
use safe metadata for paths, policy decisions, errors, usage and timings.

Approve and reject separate high-risk synthetic requests. Check that rejection
has no business write and that both outcomes are observable. Worker execution for
buffered requests keeps the intake trace ID, even when processing happens later.
