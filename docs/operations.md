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

`POST /messages` requires `X-Tenant-ID` and `X-User-ID`. M6 supports
`debounce=false`; Redis-backed buffering arrives in M7.

High-risk responses include a `checkpoint_id` and the status
`requires_confirmation`. Send the same trusted headers to one of:

```text
POST /confirmations/{checkpoint_id}/approve
POST /confirmations/{checkpoint_id}/reject
```

M6 checkpoints are process-local. Restarting the API invalidates pending
approvals; persistent checkpoint recovery is an M7 feature.

## Secrets

Use `.env` locally and `.env.example` as documentation. Never commit real secrets.
