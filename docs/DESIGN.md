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

## Phase 2 — Indian market news

- News has a normalized-URL hash constraint plus a conservative title-token similarity check inside 48 hours; tags live in a small indexed join table.
- Tagging is deterministic word-boundary matching over explicit company, ticker, index, and sector aliases; no sentiment or causal inference is attempted.
- Move days compare absolute adjusted daily return with twice the trailing 90-session standard deviation, shifted one session to keep today's return out of its threshold.
- News timestamps stay in UTC; move-day joins convert publication time to each instrument's exchange timezone, including IST for Indian instruments.
- A 365-day delete runs with ingestion. At roughly 200 short RSS records/day, a conservative 1–2 KB per record plus indexes is about 73–146 MB/year.
- ET, Mint, and Business Standard feeds were technically verified but require permission for this use; Moneycontrol returned HTTP 403, so all are disabled by default.
- The scheduled job is still useful and safe: a licensed source can be enabled by feed ID without code changes, and one failing feed produces a partial run rather than discarding others.
- The requested real 50-headline evaluation was rejected rather than copied against terms; the zero-sample limitation is explicit in `docs/news_tagging_eval.md`.
- `feedparser` is the only runtime dependency added: it handles RSS date/namespace variations more safely than a custom XML parser.

## Phase 3 — India-aware regime analogues

- Version `india-us-v1` uses a fixed ten-feature vector: Nifty return/volatility, India VIX, USD/INR, Brent, and five transformed US macro features.
- CPI and GDP become year-over-year rates rather than incomparable index/level trends; mixed-frequency macro values are only carried forward from observations dated on or before each month.
- Each month is z-scored with its own expanding history, including only that month and earlier months; at least 24 complete months are required.
- Current and future rows are excluded from analogue candidates, zero-norm vectors are rejected, and the append-a-future-outlier regression test proves earlier vectors do not change.
- Similarity is descriptive cosine similarity over named standardized features; the endpoint returns exactly three usable analogues or an explicit insufficient-history state.
- Forward outcomes use 21, 63, and 126 later Nifty trading sessions, not calendar-day guesses, with the sample size stated for every horizon.
- JSONB named vectors keep the schema explainable and versioned while preserving legacy fingerprint columns during migration.
- Current FRED revisions are not real-time vintages, so the API and UI state that this is historical analogy—not a forecast, investment advice, or true vintage backtest.

## Phase 4 — methodology and visible freshness

- `/methodology` is the single factual contract for live database counts, source cadence, formulas, validation rules, limitations, and the investment-advice disclaimer.
- `/freshness` reports every instrument and macro series separately rather than masking an old series behind a recently updated one.
- Market freshness counts weekdays so a Friday close remains fresh over the weekend; monthly and quarterly macro thresholds reflect publication cadence.
- Job freshness distinguishes the last successful completion from the last failed or partial completion, and recent detailed runs remain available separately.
- CPI is labeled as an index level in the selector; price change is labeled “30 sessions,” matching the actual calculation.
- News reports `not_configured` while publisher permission is absent instead of presenting an empty feed as a live news product.
- Dashboard loaders settle independently so a missing optional dataset does not leave otherwise healthy panels stuck in loading state.
- Marketing claims were replaced with measured database counts, explicit formulas, upstream-delay expectations, and known limitations.

## Phase 5 — tests, CI, and reproducible operation

- CI applies the complete migration chain to PostgreSQL 16, runs pytest, builds the production image, and validates Docker Compose on every push and pull request.
- Unit coverage now includes Neon retry behavior, IST dates, ticker syntax, repo-rate fixtures, URL/title dedupe, deterministic tags, move thresholds, expanding z-scores, leakage, and freshness.
- A PostgreSQL integration test executes the market upsert twice and proves the longest configured symbol remains one natural-key row.
- The health test verifies `/health` performs only one connection check and closes it; ingestion is never triggered by readiness checks.
- Compose provides one local PostgreSQL service and one API service; jobs are explicit one-shot commands so local schedules cannot accidentally duplicate production jobs.
- Poetry is pinned in the image, the curated RBI data is copied into it, and the runtime uses an unprivileged user plus an HTTP health check.
- README architecture, endpoints, source licensing, environment variables, and deployment steps now match the code and workflows.
- Full end-to-end source ingestion remains an operator action because CI must not depend on Yahoo/FRED availability or production secrets.
- `httpx` is development-only and exists solely to exercise FastAPI routes through its supported test client.
