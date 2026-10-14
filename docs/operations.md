# Operations

## Local Stack

```powershell
docker compose up --build
```

Expected services:

- API: `http://localhost:8000`
- PostgreSQL: `localhost:5432`
- Redis: `localhost:6379`

## Health Check

```powershell
Invoke-RestMethod http://localhost:8000/health
```

## Immediate Messages and Approval

`POST /messages` requires `X-Tenant-ID` and `X-User-ID`. `debounce=false`
executes immediately; `debounce=true` queues text fragments in Redis until the
configured debounce window expires. A lifespan worker processes due sessions.
Inspect the result with `GET /sessions/{session_id}/state` using the same headers.

High-risk responses include a `checkpoint_id` and the status
`requires_confirmation`. Send the same trusted headers to one of:

```text
POST /confirmations/{checkpoint_id}/approve
POST /confirmations/{checkpoint_id}/reject
```

For one action, the confirmation retains its `action` field. Multi-action
requests expose an `actions` list; approval or rejection applies to the entire
list. If there are multiple graph interrupts, `confirmation.interrupts` includes
every `interrupt_id` and its payload, and the endpoint applies the decision to
all of them.

An approval handle is consumed before resume. Unauthorized and already-consumed
handles return 404; a competing request can return 409 while the session is busy.
If resume reaches another interrupt, use
the new `checkpoint_id` returned by the API. An uncertain execution failure
returns `failed` and consumes the handle; inspect the business operation before
submitting a replacement request.

M7 stores graph checkpoints, ownership, buffers, message receipts, and session
results in Redis. Pending confirmations survive API restarts. Redis uses AOF
with `appendfsync always` and the `redis_data` volume. A tenant/session pair has
one owner and one active execution lease; unresolved confirmations block new
messages in that session. Reusing a message ID returns the saved receipt;
reusing it with different content returns `MESSAGE_ID_CONFLICT`.

An unfinished possible write is not automatically replayed after recovery.
It returns `EXECUTION_INTERRUPTED` and requires inspection. A Redis outage
returns HTTP 503 with `STATE_STORE_UNAVAILABLE`; a busy session returns 409.

See [M7 manual verification](m7-manual-test.md) for PowerShell examples and
[ADR 0007](decisions/0007-redis-conversation-durability.md) for durability limits.

## Secrets

Use `.env` locally and `.env.example` as documentation. Never commit real secrets.

## M8 observation and evaluation

- GET /metrics exports Prometheus counters/histograms; scrape it per API process.
- HTTP route labels use route templates; unknown paths use unmatched. Scrapes do
  not count themselves. Tenant/session/request IDs are never metric labels.
- Graph execution, verified tools, LLM usage and HITL have separate collectors.
- Logs use safe JSON events. User content, tool arguments, credentials and raw
  exceptions are excluded. Runtime IDs correlate events with private traces.
- Enable LANGSMITH_TRACING with local credentials/project configuration to export
  graph/model/tool spans. All nested inputs/outputs are hidden; inspect safe metadata.
- Application shutdown flushes pending traces with a bounded wait.
- LLM_INPUT_USD_PER_MILLION and LLM_OUTPUT_USD_PER_MILLION optionally enable estimates.
  Unset rates/usage mean unknown cost; estimates exclude caching/billing adjustments.
- Keep evaluation reports outside Git (evals/reports is ignored). Normal CI uploads
  replay artifacts; explicit workflow_dispatch can run live model evaluations.

Follow docs/m8-manual-test.md for metrics, logs, HITL and evaluation verification.
M8 adds no external metrics collector or multi-process aggregation service.
