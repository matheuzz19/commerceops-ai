# M7 manual verification (PowerShell)

Run from the repository root with Docker Desktop running. Keep your existing `.env`
and configure `OPENAI_API_KEY` locally. Manual API requests use the configured model;
automated tests use fixed planners and simulated tools.

## Prepare the local stack

For Docker, use the `DATABASE_URL` and `REDIS_URL` service hostnames from `.env.example`.
Keep `MESSAGE_DEBOUNCE_SECONDS=3` and `SESSION_LOCK_SECONDS=60`.

```powershell
docker compose up -d postgres redis
docker compose run --rm agent-api alembic upgrade head
docker compose run --rm agent-api python -c "from commerceops.db.session import SessionLocal; from commerceops.db.seed import seed_database; db = SessionLocal(); seed_database(db); db.commit(); db.close()"
docker compose up -d --build agent-api
```

Retrieve the synthetic Sample North tenant ID:

```powershell
$tenantId = (docker compose exec -T agent-api python -c "from commerceops.db.seed import _seed_id; print(_seed_id('tenant:sample-north'))").Trim()
$headers = @{ 'X-Tenant-ID' = $tenantId; 'X-User-ID' = 'manual-operator' }
$sessionId = 'm7-' + [guid]::NewGuid().ToString('N')
$baseUrl = 'http://localhost:8000'
```

You can also inspect the HTTP endpoints at `http://localhost:8000/docs`.

## Verify debounce and session inspection

Send fragments within the debounce window. This example reads orders and creates no business records.

```powershell
$parts = @('List orders', 'for customer', 'River Example')
foreach ($part in $parts) {
    $body = @{
        session_id = $sessionId
        message_id = [guid]::NewGuid().ToString('N')
        content = $part
        debounce = $true
    } | ConvertTo-Json
    Invoke-RestMethod "$baseUrl/messages" -Method Post -Headers $headers -ContentType 'application/json' -Body $body
}
Start-Sleep -Seconds 4
$state = Invoke-RestMethod "$baseUrl/sessions/$sessionId/state" -Headers $headers
$state | ConvertTo-Json -Depth 15
```

Expected: each POST returns `buffered`; GET eventually reports `completed`, with three
`source_message_ids`, combined content under `state.normalized_message`, and one Sales
result under `state.specialist_results`. Poll again if the model takes longer.

## Verify approval after an API restart

```powershell
$riskSession = 'm7-hitl-' + [guid]::NewGuid().ToString('N')
$body = @{
    session_id = $riskSession
    message_id = [guid]::NewGuid().ToString('N')
    content = 'Record an expense of 1200 for synthetic M7 equipment'
    debounce = $false
} | ConvertTo-Json
$pending = Invoke-RestMethod "$baseUrl/messages" -Method Post -Headers $headers -ContentType 'application/json' -Body $body
$pending | ConvertTo-Json -Depth 15
```

Expected: `requires_confirmation`; no expense has been recorded yet.

```powershell
docker compose restart agent-api
Start-Sleep -Seconds 3
Invoke-RestMethod "$baseUrl/sessions/$riskSession/state" -Headers $headers | ConvertTo-Json -Depth 15
Invoke-RestMethod "$baseUrl/confirmations/$($pending.checkpoint_id)/reject" -Method Post -Headers $headers | ConvertTo-Json -Depth 15
```

Expected: the confirmation survives restart. Rejection returns `failed` with a
non-execution explanation. For a successful write, submit a new high-risk request and
use `/approve`; it records an expense in the synthetic development database.
A consumed confirmation cannot execute again (404, or 409 while processing).

## Automated tests without model calls

```powershell
docker compose --profile test up -d postgres-test redis-test
$env:TEST_DATABASE_URL = 'postgresql+psycopg://commerceops:commerceops@localhost:5433/commerceops_test'
$env:TEST_REDIS_URL = 'redis://localhost:6380/15'
& '.\.venv\Scripts\python.exe' -m pytest tests/unit tests/integration tests/contract tests/evals
docker compose --profile test stop postgres-test redis-test
```

Tests delete only their own Redis prefixes in database 15. Development Redis has
AOF persistence in `redis_data`. Interrupted possible writes are reported as
`EXECUTION_INTERRUPTED` and require inspection; they are never automatically replayed.
