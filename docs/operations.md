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

## Secrets

Use `.env` locally and `.env.example` as documentation. Never commit real secrets.
