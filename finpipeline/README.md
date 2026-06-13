# finpipeline

A financial data pipeline I built from scratch — pulls real stock and macro data, runs analytics, exposes everything through a REST API, and deploys on Railway with Docker.

The idea was to build something that actually does useful work: fetch data from Yahoo Finance and the FRED API, store it in Postgres, analyse it, and serve it. Not a tutorial project — the data is real, the API is live, and the analysis has genuine signal.

---

## What it does

- Pulls daily OHLCV stock prices for AAPL, GOOGL, MSFT, TSLA from Yahoo Finance
- Pulls macro indicators (CPI, Fed Funds Rate, Unemployment, GDP, Yield Curve) from FRED
- Stores everything in a Postgres database with proper schema and migrations
- Runs analytics: rolling averages, annualised volatility, market summary
- Classifies the current macro environment into a regime (expansionary / transitional / contractionary)
- Finds historical periods that look similar to today using cosine similarity
- Estimates forward stock returns based on what happened after those similar periods
- Backtests the regime classification to check whether it actually predicts anything
- Serves all of this through a FastAPI REST API with JWT authentication and rate limiting
- Runs on a schedule — stock data at 6pm daily, macro data Monday mornings
- Deployed on Railway with Docker, live at `https://finpipeline-production.up.railway.app`

---

## Live API

**Base URL:** `https://finpipeline-production.up.railway.app`

### Public endpoints

| Endpoint | What it returns |
|---|---|
| `GET /health` | API and database status |
| `GET /metrics` | Row counts, latest data date, pipeline run history |
| `GET /stocks/summary` | Latest price + 30-day change for all tickers |
| `GET /docs` | Interactive API docs (Swagger UI) |

### Protected endpoints — require `Authorization: Bearer <token>`

| Endpoint | What it returns |
|---|---|
| `GET /analysis/regime` | Current macro regime fingerprint |
| `GET /analysis/outlook?ticker=AAPL` | Forward return estimate based on similar historical periods |
| `GET /analysis/backtest?ticker=AAPL` | Backtest of regime classification vs actual returns |
| `GET /stocks/{ticker}/history` | OHLCV data for a date range |
| `GET /stocks/{ticker}/volatility` | Annualised volatility over N days |
| `GET /stocks/{ticker}/rolling-average` | Close price with rolling average overlay |
| `GET /macro/{indicator}` | Economic indicator history |
| `GET /pipeline/runs` | History of data fetch runs |

### Auth endpoints

```bash
# get a token
curl -X POST https://finpipeline-production.up.railway.app/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "adminpassword123"}'

# use the token
curl https://finpipeline-production.up.railway.app/analysis/regime \
  -H "Authorization: Bearer YOUR_TOKEN"
```

---

## How the macro analysis works

Each month gets a "fingerprint" — a vector of 5 percentile scores, one per indicator. A CPI at the 95th percentile means inflation is higher than 95% of all historical readings. That makes the indicators comparable to each other even though their raw values are on completely different scales.

The engine then classifies each month as one of three regimes:
- **Expansionary** — low macro stress, generally good for risk assets
- **Transitional** — mixed signals, some elevated indicators
- **Contractionary** — high macro stress, elevated inflation or rates or unemployment

To generate an outlook for a stock, it finds the most similar historical months using cosine similarity, then looks up what the stock actually did in the 60 trading days after each of those periods. The backtest endpoint checks whether this approach has real predictive value — spoiler: it does for AAPL, TSLA, and GOOGL, but MSFT tends to be resilient across all regimes.

---

## Daily build log

This project was built one day at a time. Each day added a concrete, working layer.

| Day | Focus | What was built |
|---|---|---|
| 1 | Setup | Poetry project, `.env`, Postgres connection, basic schema |
| 2 | Data fetching | Yahoo Finance → Postgres via `yfinance` |
| 3 | Macro data | FRED API → Postgres for CPI, Fed Funds, Unemployment, GDP, Yield Curve |
| 4 | Database migrations | Alembic setup, versioned schema changes |
| 5 | Analytics | Rolling averages, annualised volatility, market summary queries |
| 6 | REST API | FastAPI app, all data endpoints, input validation |
| 7 | Macro regime engine | Percentile fingerprinting, cosine similarity, forward return estimates |
| 8 | Backtesting | Regime classification vs actual returns, regime hit-rate validation |
| 9 | Scheduler | APScheduler — stock pipeline at 6pm daily, macro on Monday mornings |
| 10 | Docker + Railway | Dockerfile, `railway.toml`, live deployment |
| 11 | Observability | Structured JSON logging, `/metrics` endpoint, pipeline run tracking |
| 12 | Security | JWT auth, bcrypt password hashing, rate limiting (slowapi), secrets audit |

---

## Project structure

```
src/
├── config.py          # loads env vars, never hardcode credentials
├── db.py              # postgres connection
├── auth.py            # JWT creation/verification, bcrypt hashing, auth dependency
├── analytics.py       # rolling averages, volatility, market summary
├── regime.py          # macro fingerprinting, similarity search, forward returns
├── backtest.py        # regime backtest validation
├── seed.py            # test data
├── api.py             # FastAPI app, all endpoints, scheduler, rate limiting
└── fetchers/
    ├── stock_fetcher.py   # Yahoo Finance → Postgres
    └── macro_fetcher.py   # FRED API → Postgres

migrations/            # Alembic migration files
dashboard/
└── index.html         # frontend dashboard (vanilla JS + Chart.js)
```

---

## Running locally

You need Python 3.11+, Poetry, and Postgres running locally.

```bash
# install dependencies
poetry install

# set up your .env
# DB_HOST=localhost
# DB_PORT=5432
# DB_NAME=finpipeline
# DB_USER=your_username
# DB_PASSWORD=
# FRED_API_KEY=your_key_from_fred.stlouisfed.org
# SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
# ALGORITHM=HS256
# ACCESS_TOKEN_EXPIRE_MINUTES=60

# create the database
psql postgres -c "CREATE DATABASE finpipeline;"

# run migrations
poetry run alembic upgrade head

# fetch data
PYTHONPATH=. poetry run python src/fetchers/stock_fetcher.py
PYTHONPATH=. poetry run python src/fetchers/macro_fetcher.py

# build macro fingerprints
PYTHONPATH=. poetry run python -c "from src.regime import store_fingerprints; store_fingerprints()"

# start the API
PYTHONPATH=. poetry run uvicorn src.api:app --reload --port 8000
```

Open `http://localhost:8000/docs` to explore the API. Click **Authorize** (top right) and paste your JWT to test protected endpoints.

---

## Running with Docker

```bash
# build (run from repo root)
docker build -t finpipeline -f finpipeline/Dockerfile .

# run (pass your DB credentials as env vars)
docker run -p 8000:8000 \
  -e DB_HOST=host.docker.internal \
  -e DB_PORT=5432 \
  -e DB_NAME=finpipeline \
  -e DB_USER=your_username \
  -e DB_PASSWORD= \
  -e FRED_API_KEY=your_key \
  -e SECRET_KEY=your_secret_key \
  -e ALGORITHM=HS256 \
  -e ACCESS_TOKEN_EXPIRE_MINUTES=60 \
  finpipeline
```

---

## Tech stack

- **Python 3.11** — core language
- **FastAPI** — REST API framework
- **PostgreSQL** — database
- **psycopg2** — postgres driver
- **Alembic** — database migrations
- **yfinance** — Yahoo Finance data
- **pandas / numpy** — data processing
- **scikit-learn** — cosine similarity for regime matching
- **APScheduler** — scheduled pipeline jobs
- **python-jose** — JWT creation and verification
- **bcrypt** — password hashing
- **slowapi** — rate limiting
- **Poetry** — dependency management
- **Docker** — containerisation
- **Railway** — cloud deployment
