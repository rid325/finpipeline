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
