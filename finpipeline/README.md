# Application package

Run commands from the repository root; the canonical setup, architecture, deployment, data-source, API, test, and limitation documentation is in [`../README.md`](../README.md).

Key package paths:

- `src/api.py` — FastAPI routes and optional local scheduler
- `src/jobs.py` — one-shot market, macro, news, and regime jobs
- `src/instruments.py` — database-backed instrument/series registries
- `src/news.py` — RSS metadata ingestion, dedupe, tags, and move-day joins
- `src/regime_v2.py` — no-lookahead India/US analogy engine
- `src/methodology.py` — freshness and methodology contracts
- `migrations/` — complete Alembic schema history
- `dashboard/index.html` — build-free dashboard
- `tests/` — unit, API, leakage, and optional PostgreSQL integration coverage
