# Design decisions

## Phase 0 — durable hosting and independent schedules

- Runtime requests and short jobs use Neon's pooled URL; Alembic and database backups use the direct URL because those operations require stable sessions.
- The existing psycopg2 driver now verifies each new connection with `SELECT 1` and retries briefly, covering Neon cold starts without introducing SQLAlchemy.
- GitHub Actions owns production schedules, so Render sleep cannot skip ingestion; APScheduler remains available but defaults off to prevent duplicate runs.
- Market and macro jobs are CLI processes with meaningful exit codes, bounded workflow timeouts, and concurrency guards.
- Inserts remain idempotent through existing natural-key constraints, so retries do not duplicate observations.
- Pipeline runs now record a stable job name and elapsed milliseconds in addition to source, status, row count, and error text.
- GitHub may disable public-repository schedules after 60 days without repository activity; workflows include manual dispatch, but the owner must monitor this outside GitHub.
- Tradeoff: the free Render API can still cold-start slowly, but persistence and schedules no longer depend on that web process.

## Phase 1 — India market layer

- Instruments and macro series are seeded into database registries, so jobs, validation, filters, and the UI read one source of truth instead of separate hard-coded lists.
- The 16 India-context and four global symbols were retained only after a live Yahoo/yfinance check returned recent daily observations.
- Yahoo is called with adjustment disabled; raw OHLC and adjusted close are both stored, while return and volatility calculations use adjusted close.
- Daily bars retain the exchange-local session date, preventing an Indian midnight timestamp from shifting to the prior UTC day; absent holiday rows are normal.
- The daily job re-fetches ten calendar days so upstream revisions are updated idempotently; a five-year backfill is an explicit CLI option and never blocks API startup.
- Seven India FRED series were live-verified. RBI policy repo values are a small manually curated CSV with an official source URL and as-of date on every row.
- The RBI CSV was chosen over scraping DBIE; the tradeoff is deliberate manual maintenance, which is labeled in both registry and API output.
- `stock_prices.ticker` and price precision were widened for real Yahoo symbols; a foreign key was deferred to avoid breaking legacy custom rows.
