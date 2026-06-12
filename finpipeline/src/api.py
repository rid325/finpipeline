# src/api.py
from fastapi import FastAPI, HTTPException, Query, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
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

VALID_TICKERS = {'AAPL', 'GOOGL', 'MSFT', 'TSLA'}
VALID_INDICATORS = {'CPI', 'FEDFUNDS', 'UNRATE', 'GDP', 'T10Y2Y'}

scheduler = AsyncIOScheduler()


# ── scheduled pipeline jobs ────────────────────────────────────────────────
def run_stock_pipeline():
    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    logger.info("Scheduled stock pipeline starting...")
    result = fetch_and_store_stocks(['AAPL', 'GOOGL', 'MSFT', 'TSLA'], start, end)
    logger.info(f"Scheduled stock pipeline done: {result['total_inserted']} records, errors: {result['errors'] or 'none'}")


def run_macro_pipeline():
    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d')
    logger.info("Scheduled macro pipeline starting...")
    result = fetch_and_store_indicators(start, end)
    logger.info(f"Scheduled macro pipeline done: {result['total_inserted']} records")


def run_regime_update():
    logger.info("Updating macro fingerprints...")
    store_fingerprints()
    logger.info("Macro fingerprints updated")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting finpipeline API")
    scheduler.add_job(run_stock_pipeline, 'cron', hour=18, minute=0)
    scheduler.add_job(run_macro_pipeline, 'cron', day_of_week='mon', hour=9)
    scheduler.add_job(run_regime_update, 'cron', hour=19, minute=0)
    scheduler.start()
    logger.info("Scheduler started")
    yield
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
@app.get("/health")
def health_check():
    """Check if API and database are reachable."""
    try:
        conn = get_connection()
        conn.close()
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {e}")


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
        cursor.close()
        conn.close()

        return {
            "database": {
                "stock_prices_count": stock_count,
                "economic_indicators_count": indicator_count,
                "latest_stock_date": str(latest_stock_date) if latest_stock_date else None
            },
            "pipeline": pipeline_stats
        }
    except Exception as e:
        logger.error(f"Error fetching metrics: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/stocks/summary")
def market_summary():
    """Latest price and 30-day change for all tracked tickers."""
    try:
        data = get_market_summary(list(VALID_TICKERS))
        return {"count": len(data), "data": data}
    except Exception as e:
        logger.error(f"Error fetching market summary: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/stocks/{ticker}/history")
def price_history(
    ticker: str,
    start_date: str = Query(default="2024-01-01"),
    end_date: str = Query(default="2024-06-01")
):
    """OHLCV price history for a ticker."""
    ticker = ticker.upper()
    if ticker not in VALID_TICKERS:
        raise HTTPException(status_code=404, detail=f"Ticker {ticker} not found. Valid: {sorted(VALID_TICKERS)}")
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
    ticker = ticker.upper()
    if ticker not in VALID_TICKERS:
        raise HTTPException(status_code=404, detail=f"Ticker {ticker} not found")
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
    ticker = ticker.upper()
    if ticker not in VALID_TICKERS:
        raise HTTPException(status_code=404, detail=f"Ticker {ticker} not found")
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
    if indicator not in VALID_INDICATORS:
        raise HTTPException(status_code=404, detail=f"Indicator {indicator} not found. Valid: {sorted(VALID_INDICATORS)}")
    try:
        data = get_indicator_history(indicator, start_date, end_date)
        if not data:
            raise HTTPException(status_code=404, detail="No data found for this date range")
        return {"indicator": indicator, "count": len(data), "data": data}
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
            SELECT id, source, status, records_fetched, error_message, started_at, completed_at
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
                 "completed_at": str(row[6]) if row[6] else None}
                for row in rows
            ]
        }
    except Exception as e:
        logger.error(f"Error fetching pipeline runs: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


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
    ticker = ticker.upper()
    if ticker not in VALID_TICKERS:
        raise HTTPException(status_code=404, detail=f"Ticker {ticker} not found")
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
    ticker = ticker.upper()
    if ticker not in VALID_TICKERS:
        raise HTTPException(status_code=404, detail=f"Ticker {ticker} not found")
    try:
        return run_regime_backtest(ticker, horizon_days=horizon)
    except Exception as e:
        logger.error(f"Backtest error for {ticker}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
