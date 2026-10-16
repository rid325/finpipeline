# FinPipeline

FinPipeline is a production-oriented financial data pipeline and analytics API. It ingests market data from Yahoo Finance and macroeconomic series from FRED, stores them in PostgreSQL, and exposes analytics, regime classification, similarity search, and backtesting through FastAPI.

> **Deployment status:** the previous Railway service is offline. The repository is deployment-ready, but no live URL is claimed until a replacement service is verified.

## Highlights

- Scheduled stock and macro ingestion with auditable pipeline runs
- Rolling averages, annualized volatility, and market summaries
- Macro regime fingerprints and cosine-similarity historical search
- Forward-return analysis and regime backtesting
- PostgreSQL migrations with Alembic
- JWT authentication, input validation, rate limiting, and structured logs
- Docker and Railway configuration with runtime port and `DATABASE_URL` support

## Architecture

```text
Yahoo Finance ─┐
               ├─> ingestion jobs ─> PostgreSQL ─> analytics/regime engine ─> FastAPI
FRED API ──────┘
```

The application source, detailed API reference, dashboard, and full local setup guide are in [`finpipeline/`](finpipeline/README.md).

## Deploying on Railway

1. Create a Railway project from this repository and add a PostgreSQL service.
2. Set `DATABASE_URL` to the PostgreSQL reference variable exposed by Railway.
3. Add `SECRET_KEY`, `FRED_API_KEY`, `AUTH_USERNAME`, and `AUTH_PASSWORD` as service variables.
4. Deploy. `railway.toml` runs migrations before startup and binds Uvicorn to Railway's assigned `PORT`.
5. Verify `/health` and `/docs`, then add the confirmed public URL to this README.

No demo password is stored in the repository. If `AUTH_USERNAME` or `AUTH_PASSWORD` is absent, login remains disabled.

## Local quick start

```bash
poetry install --no-root
export DB_USER=postgres
export SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
cd finpipeline
poetry run alembic upgrade head
PYTHONPATH=. poetry run uvicorn src.api:app --reload --port 8000
```

See the [complete documentation](finpipeline/README.md) for ingestion, environment variables, Docker, and endpoint details.
