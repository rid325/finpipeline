# src/api.py
from fastapi import FastAPI, HTTPException, Query, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from pydantic import BaseModel
from datetime import datetime, timedelta
import time
import logging
import json
from pathlib import Path

from src.analytics import (
    get_price_history,
    get_rolling_average,
    get_volatility,
    get_indicator_history,
    get_market_summary
)
from src.db import get_connection
from src.regime import get_macro_fingerprint, get_similar_periods, get_forward_returns, store_fingerprints
from src.backtest import run_regime_backtest
from src.auth import verify_password, create_access_token, get_current_user, USERS
from src.fetchers.stock_fetcher import fetch_and_store_stocks
from src.fetchers.macro_fetcher import fetch_and_store_indicators
from src.validators import validate_date, validate_date_range, validate_ticker
from src.config import ENABLE_APSCHEDULER
from src.instruments import list_instruments, list_macro_series
from src.news import FEEDS, get_move_days, query_news
from src.regime_v2 import compute_regime_current
from src.methodology import get_freshness, get_methodology


# ── structured JSON logging ────────────────────────────────────────────────
class JSONFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            'timestamp': self.formatTime(record),
            'level': record.levelname,
            'message': record.getMessage(),
            'module': record.module
        })

handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logging.basicConfig(level=logging.INFO, handlers=[handler])
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()
DASHBOARD_PATH = Path(__file__).resolve().parent.parent / "dashboard" / "index.html"


# ── scheduled pipeline jobs ────────────────────────────────────────────────
def run_stock_pipeline():
    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    logger.info("Scheduled stock pipeline starting...")
    instruments = list_instruments()
    result = fetch_and_store_stocks(
        [item['ticker'] for item in instruments], start, end, job_name="market-all",
        timezones={item['ticker']: item['timezone'] for item in instruments}
    )
    logger.info(f"Scheduled stock pipeline done: {result['total_inserted']} records, errors: {result['errors'] or 'none'}")


def seed_stock_history_if_empty():
    """Populate missing tickers without delaying API startup."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT DISTINCT ticker FROM stock_prices")
        present_tickers = {row[0] for row in cursor.fetchall()}
        registry = {item['ticker']: item for item in list_instruments()}
        missing_tickers = sorted(set(registry) - present_tickers)
        if not missing_tickers:
            logger.info("Stock history already present; skipping bootstrap ingestion")
            return
    finally:
        cursor.close()
        conn.close()

    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
    logger.info(f"Bootstrapping missing stock history for: {missing_tickers}")
    result = fetch_and_store_stocks(
        missing_tickers, start, end, job_name="market-bootstrap",
        timezones={ticker: registry[ticker]['timezone'] for ticker in missing_tickers}
    )
    logger.info(
        f"Bootstrap stock ingestion done: {result['total_inserted']} records, "
        f"errors: {result['errors'] or 'none'}"
    )


def seed_macro_history_if_empty():
    """Populate five years of macro history using FRED API or its CSV feed."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM economic_indicators")
        if cursor.fetchone()[0] > 0:
            logger.info("Macro history already present; skipping bootstrap ingestion")
            return
    finally:
        cursor.close()
        conn.close()

    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=365 * 5)).strftime('%Y-%m-%d')
    logger.info("Fresh database detected; bootstrapping five years of macro history")
    result = fetch_and_store_indicators(start, end, job_name="macro-bootstrap")
    logger.info(
        f"Bootstrap macro ingestion done: {result['total_inserted']} records, "
        f"errors: {result['errors'] or 'none'}"
    )


def run_macro_pipeline():
    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d')
    logger.info("Scheduled macro pipeline starting...")
    result = fetch_and_store_indicators(start, end, job_name="macro-all")
    logger.info(f"Scheduled macro pipeline done: {result['total_inserted']} records")


def run_regime_update():
    logger.info("Updating macro fingerprints...")
    store_fingerprints()
    logger.info("Macro fingerprints updated")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting finpipeline API")
    if ENABLE_APSCHEDULER:
        scheduler.add_job(run_stock_pipeline, 'cron', hour=18, minute=0)
        scheduler.add_job(run_macro_pipeline, 'cron', day_of_week='mon', hour=9)
        scheduler.add_job(run_regime_update, 'cron', hour=19, minute=0)
        scheduler.add_job(
            seed_stock_history_if_empty, 'date',
            run_date=datetime.now() + timedelta(seconds=5),
            id='bootstrap-stocks', replace_existing=True
        )
        scheduler.add_job(
            seed_macro_history_if_empty, 'date',
            run_date=datetime.now() + timedelta(seconds=15),
            id='bootstrap-macro', replace_existing=True
        )
        scheduler.add_job(
            run_regime_update, 'date',
            run_date=datetime.now() + timedelta(seconds=90),
            id='bootstrap-regimes', replace_existing=True
        )
        scheduler.start()
        logger.info("APScheduler started")
    else:
        logger.info("APScheduler disabled; external jobs own production schedules")
    yield
    if scheduler.running:
        scheduler.shutdown()
    logger.info("Shutting down finpipeline API")


app = FastAPI(
    title="Financial Data Pipeline API",
    description="Stock prices, macro indicators, and analytics",
    version="0.1.0",
    lifespan=lifespan
)

# ── rate limiter ───────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── request logging middleware ─────────────────────────────────────────────
@app.middleware("http")
async def log_requests(request, call_next):
    start = time.time()
    response = await call_next(request)
    duration_ms = round((time.time() - start) * 1000, 2)
    logger.info(f"{request.method} {request.url.path} → {response.status_code} ({duration_ms}ms)")
    return response


# ── auth endpoints (public) ────────────────────────────────────────────────
class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/auth/login")
def login(request: LoginRequest):
    """Get a JWT token. Pass it as Authorization: Bearer <token> on protected endpoints."""
    user = USERS.get(request.username)
    if not user or not verify_password(request.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = create_access_token({"sub": request.username})
    return {"access_token": token, "token_type": "bearer"}


@app.get("/auth/me")
def me(current_user: str = Depends(get_current_user)):
    """Verify your token and see who you're authenticated as."""
    return {"username": current_user}


# ── public endpoints ───────────────────────────────────────────────────────
@app.get("/")
def service_info():
    """Serve the live dashboard at the public deployment URL."""
    return FileResponse(DASHBOARD_PATH)


@app.get("/api")
def api_info():
    """Machine-readable service discovery response."""
    return {
        "service": "FinPipeline",
        "status": "online",
        "description": "Financial data pipeline and analytics API",
        "health": "/health",
        "documentation": "/docs"
    }


@app.get("/health")
def health_check():
    """Check if API and database are reachable."""
    try:
        conn = get_connection()
        conn.close()
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Database unavailable")


@app.get("/metrics")
def metrics():
    """Basic API and pipeline health metrics."""
    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM stock_prices")
        stock_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM economic_indicators")
        indicator_count = cursor.fetchone()[0]

        cursor.execute("""
            SELECT source, MAX(completed_at) as last_run, SUM(records_fetched) as total_fetched
            FROM pipeline_runs WHERE status = 'success' GROUP BY source
        """)
        pipeline_stats = [
            {'source': row[0], 'last_successful_run': str(row[1]) if row[1] else None,
             'total_records_fetched': int(row[2])}
            for row in cursor.fetchall()
        ]

        cursor.execute("SELECT MAX(date) FROM stock_prices")
        latest_stock_date = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM instruments WHERE active=TRUE")
        instrument_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM macro_series WHERE active=TRUE")
        series_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM news_articles")
        news_count = cursor.fetchone()[0]
        cursor.close()
        conn.close()

        return {
            "database": {
                "stock_prices_count": stock_count,
                "economic_indicators_count": indicator_count,
                "latest_stock_date": str(latest_stock_date) if latest_stock_date else None,
                "active_instruments_count": instrument_count,
                "active_macro_series_count": series_count,
                "news_articles_count": news_count,
            },
            "pipeline": pipeline_stats
        }
    except Exception as e:
        logger.error(f"Error fetching metrics: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/stocks/summary")
def market_summary(market: str = Query(default="india", pattern="^(india|global)$")):
    """Latest price and 30-day change for all tracked tickers."""
    try:
        instruments = list_instruments(market)
        metadata = {item['ticker']: item for item in instruments}
        data = get_market_summary(list(metadata))
        for row in data:
            row.update({key: metadata[row['ticker']][key] for key in (
                'display_name', 'market', 'asset_type', 'currency', 'exchange', 'sector'
            )})
        return {"market": market, "count": len(data), "data": data}
    except Exception as e:
        logger.error(f"Error fetching market summary: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/instruments")
def instruments(market: str = Query(default="india", pattern="^(india|global)$")):
    """Active instruments from the database-backed registry."""
    data = list_instruments(market)
    return {"market": market, "count": len(data), "data": data}


def _valid_tickers() -> set[str]:
    return {item['ticker'] for item in list_instruments()}


@app.get("/stocks/{ticker}/history")
def price_history(
    ticker: str,
    start_date: str = Query(default="2024-01-01"),
    end_date: str = Query(default="2024-06-01"),
    current_user: str = Depends(get_current_user)
):
    """OHLCV price history for a ticker. Requires auth."""
    ticker = validate_ticker(ticker, _valid_tickers())
    validate_date(start_date, "start_date")
    validate_date(end_date, "end_date")
    validate_date_range(start_date, end_date)
    try:
        data = get_price_history(ticker, start_date, end_date)
        if not data:
            raise HTTPException(status_code=404, detail="No data found for this date range")
        return {"ticker": ticker, "count": len(data), "data": data}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching history for {ticker}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/stocks/{ticker}/rolling-average")
def rolling_average(
    ticker: str,
    window: int = Query(default=30, ge=2, le=200)
):
    """Closing price with rolling average overlay."""
    ticker = validate_ticker(ticker, _valid_tickers())
    try:
        data = get_rolling_average(ticker, window)
        return {"ticker": ticker, "window": window, "count": len(data), "data": data}
    except Exception as e:
        logger.error(f"Error fetching rolling average for {ticker}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/stocks/{ticker}/volatility")
def volatility(
    ticker: str,
    days: int = Query(default=30, ge=5, le=365)
):
    """Annualized volatility for a ticker."""
    ticker = validate_ticker(ticker, _valid_tickers())
    try:
        return get_volatility(ticker, days)
    except Exception as e:
        logger.error(f"Error calculating volatility for {ticker}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/macro/{indicator}")
def indicator_history(
    indicator: str,
    start_date: str = Query(default="2020-01-01"),
    end_date: str = Query(default="2024-06-01")
):
    """Economic indicator history."""
    indicator = indicator.upper()
    series = {item['indicator']: item for item in list_macro_series()}
    if indicator not in series:
        raise HTTPException(status_code=404, detail=f"Indicator {indicator} not found. Valid: {sorted(series)}")
    validate_date(start_date, "start_date")
    validate_date(end_date, "end_date")
    validate_date_range(start_date, end_date)
    try:
        data = get_indicator_history(indicator, start_date, end_date)
        if not data:
            raise HTTPException(status_code=404, detail="No data found for this date range")
        return {"indicator": indicator, **series[indicator], "count": len(data), "data": data}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching indicator {indicator}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/pipeline/runs")
def pipeline_runs(limit: int = Query(default=10, ge=1, le=100)):
    """Recent pipeline run history."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, source, status, records_fetched, error_message,
                   started_at, completed_at, job_name, duration_ms
            FROM pipeline_runs ORDER BY started_at DESC LIMIT %s
        """, (limit,))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return {
            "count": len(rows),
            "runs": [
                {"id": row[0], "source": row[1], "status": row[2], "records_fetched": row[3],
                 "error_message": row[4], "started_at": str(row[5]),
                 "completed_at": str(row[6]) if row[6] else None,
                 "job_name": row[7], "duration_ms": row[8]}
                for row in rows
            ]
        }
    except Exception as e:
        logger.error(f"Error fetching pipeline runs: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/news")
def news(
    ticker: str | None = None,
    sector: str | None = None,
    from_date: str | None = Query(default=None, alias="from"),
    to_date: str | None = Query(default=None, alias="to"),
    source: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
):
    """Licensed-opt-in Indian market headlines and deterministic tags."""
    if from_date:
        validate_date(from_date, "from")
    if to_date:
        validate_date(to_date, "to")
    data = query_news(ticker, sector, from_date, to_date, source, limit)
    return {
        "count": len(data), "data": data,
        "source_status": {feed: details["status"] for feed, details in FEEDS.items()},
    }


@app.get("/moves")
def moves(
    ticker: str = Query(default="^NSEI"),
    days: int = Query(default=365, ge=30, le=1825),
):
    """Move days and same-day tagged headlines; no causal claim is made."""
    ticker = validate_ticker(ticker, _valid_tickers())
    data = get_move_days(ticker, days)
    return {
        "ticker": ticker, "count": len(data), "data": data,
        "definition": "absolute daily adjusted return above 2x trailing 90-session standard deviation",
        "headline_label": "headlines on the day; not evidence of cause",
    }


@app.get("/regime/current")
def india_regime_current():
    """India-aware historical analogues with no-lookahead expanding scaling."""
    try:
        return compute_regime_current()
    except Exception as error:
        logger.error(f"Error computing India regime: {error}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/freshness")
def freshness():
    """Per-instrument, per-series, and per-job freshness without hiding stale data."""
    return get_freshness()


@app.get("/methodology")
def methodology():
    """Machine-readable formulas, sources, validation, and limitations."""
    return get_methodology()


# ── protected analysis endpoints ───────────────────────────────────────────
@app.get("/analysis/regime")
def current_regime(current_user: str = Depends(get_current_user)):
    """Current macro regime fingerprint. Requires auth."""
    try:
        return get_macro_fingerprint()
    except Exception as e:
        logger.error(f"Error computing regime: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/analysis/outlook")
@limiter.limit("10/minute")
def stock_outlook(
    request: Request,
    ticker: str = Query(description="Stock ticker e.g. AAPL"),
    horizon: int = Query(default=60, ge=20, le=120),
    n_similar: int = Query(default=8, ge=3, le=20),
    current_user: str = Depends(get_current_user)
):
    """Forward return estimate based on similar historical macro periods. Requires auth."""
    ticker = validate_ticker(ticker, _valid_tickers())
    try:
        similar = get_similar_periods(n=n_similar)
        if not similar:
            raise HTTPException(status_code=404, detail="No similar historical periods found")
        returns = get_forward_returns(similar, ticker, horizon_days=horizon)
        regime = get_macro_fingerprint()
        return {
            'ticker': ticker,
            'current_regime': {
                'label': regime['regime'],
                'stress_score': regime['overall_stress_score'],
                'description': regime['regime_description']
            },
            'similar_periods': similar[:5],
            'forward_returns': returns
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error computing outlook for {ticker}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/analysis/backtest")
@limiter.limit("5/minute")
def regime_backtest(
    request: Request,
    ticker: str = Query(description="Stock ticker"),
    horizon: int = Query(default=60, ge=20, le=120),
    current_user: str = Depends(get_current_user)
):
    """Backtest regime classification vs actual returns. Requires auth."""
    ticker = validate_ticker(ticker, _valid_tickers())
    try:
        return run_regime_backtest(ticker, horizon_days=horizon)
    except Exception as e:
        logger.error(f"Backtest error for {ticker}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
