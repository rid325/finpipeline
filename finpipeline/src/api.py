# src/api.py
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
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

# valid tickers and indicators your API supports
VALID_TICKERS = {'AAPL', 'GOOGL', 'MSFT', 'TSLA'}
VALID_INDICATORS = {'CPI', 'FEDFUNDS', 'UNRATE', 'GDP', 'T10Y2Y'}

scheduler = AsyncIOScheduler()


# ── scheduled pipeline jobs ────────────────────────────────────────────────
def run_stock_pipeline():
    """Fetch last 7 days of stock data."""
    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    logger.info("Scheduled stock pipeline starting...")
    result = fetch_and_store_stocks(['AAPL', 'GOOGL', 'MSFT', 'TSLA'], start, end)
    logger.info(f"Scheduled stock pipeline done: {result['total_inserted']} records, errors: {result['errors'] or 'none'}")


def run_macro_pipeline():
    """Fetch latest macro data."""
    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d')
    logger.info("Scheduled macro pipeline starting...")
    result = fetch_and_store_indicators(start, end)
    logger.info(f"Scheduled macro pipeline done: {result['total_inserted']} records")


# ── lifespan: startup + shutdown ───────────────────────────────────────────
def run_regime_update():
    """Recompute and store macro fingerprints after new data arrives."""
    logger.info("Updating macro fingerprints...")
    store_fingerprints()
    logger.info("Macro fingerprints updated")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting finpipeline API")
    scheduler.add_job(run_stock_pipeline, 'cron', hour=18, minute=0)
    scheduler.add_job(run_macro_pipeline, 'cron', day_of_week='mon', hour=9)
    scheduler.add_job(run_regime_update, 'cron', hour=19, minute=0)  # after stock pipeline
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

# allow browser requests (needed when you add a frontend later)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── middleware: log every request with timing ──────────────────────────────
@app.middleware("http")
async def log_requests(request, call_next):
    start = time.time()
    response = await call_next(request)
    duration_ms = round((time.time() - start) * 1000, 2)
    logger.info(f"{request.method} {request.url.path} → {response.status_code} ({duration_ms}ms)")
    return response


# ── health check ───────────────────────────────────────────────────────────
@app.get("/health")
def health_check():
    """Check if API and database are reachable."""
    try:
        conn = get_connection()
        conn.close()
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {e}")


# ── metrics ────────────────────────────────────────────────────────────────
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
            FROM pipeline_runs
            WHERE status = 'success'
            GROUP BY source
        """)
        pipeline_stats = [
            {
                'source': row[0],
                'last_successful_run': str(row[1]) if row[1] else None,
                'total_records_fetched': int(row[2])
            }
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


# ── stock endpoints ────────────────────────────────────────────────────────
@app.get("/stocks/{ticker}/history")
def price_history(
    ticker: str,
    start_date: str = Query(default="2024-01-01", description="Start date YYYY-MM-DD"),
    end_date: str = Query(default="2024-06-01", description="End date YYYY-MM-DD")
):
    """OHLCV price history for a ticker."""
    ticker = ticker.upper()
    if ticker not in VALID_TICKERS:
        raise HTTPException(
            status_code=404,
            detail=f"Ticker {ticker} not found. Valid tickers: {sorted(VALID_TICKERS)}"
        )
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
    window: int = Query(default=30, ge=2, le=200, description="Rolling window in days")
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
    days: int = Query(default=30, ge=5, le=365, description="Lookback period in days")
):
    """Annualized volatility for a ticker."""
    ticker = ticker.upper()
    if ticker not in VALID_TICKERS:
        raise HTTPException(status_code=404, detail=f"Ticker {ticker} not found")
    try:
        data = get_volatility(ticker, days)
        return data
    except Exception as e:
        logger.error(f"Error calculating volatility for {ticker}: {e}")
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


# ── macro endpoints ────────────────────────────────────────────────────────
@app.get("/macro/{indicator}")
def indicator_history(
    indicator: str,
    start_date: str = Query(default="2020-01-01"),
    end_date: str = Query(default="2024-06-01")
):
    """Economic indicator history."""
    indicator = indicator.upper()
    if indicator not in VALID_INDICATORS:
        raise HTTPException(
            status_code=404,
            detail=f"Indicator {indicator} not found. Valid: {sorted(VALID_INDICATORS)}"
        )
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


# ── pipeline status ────────────────────────────────────────────────────────
@app.get("/pipeline/runs")
def pipeline_runs(limit: int = Query(default=10, ge=1, le=100)):
    """Recent pipeline run history."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, source, status, records_fetched, error_message, started_at, completed_at
            FROM pipeline_runs
            ORDER BY started_at DESC
            LIMIT %s
        """, (limit,))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        return {
            "count": len(rows),
            "runs": [
                {
                    "id": row[0],
                    "source": row[1],
                    "status": row[2],
                    "records_fetched": row[3],
                    "error_message": row[4],
                    "started_at": str(row[5]),
                    "completed_at": str(row[6]) if row[6] else None
                }
                for row in rows
            ]
        }
    except Exception as e:
        logger.error(f"Error fetching pipeline runs: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

# ── analysis endpoints ─────────────────────────────────────────────────────
@app.get("/analysis/regime")
def current_regime():
    """Current macro regime fingerprint."""
    try:
        return get_macro_fingerprint()
    except Exception as e:
        logger.error(f"Error computing regime: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/analysis/outlook")
def stock_outlook(
    ticker: str = Query(description="Stock ticker e.g. AAPL"),
    horizon: int = Query(default=60, ge=20, le=120, description="Forward horizon in trading days"),
    n_similar: int = Query(default=8, ge=3, le=20, description="Number of similar periods to use")
):
    """
    Given the current macro environment, find historically similar periods
    and return how the stock performed in the following horizon days.
    """
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
def regime_backtest(
    ticker: str = Query(description="Stock ticker"),
    horizon: int = Query(default=60, ge=20, le=120)
):
    """
    Backtest the regime classification against historical stock returns.
    Shows whether the current regime label has predictive value for this ticker.
    """
    ticker = ticker.upper()
    if ticker not in VALID_TICKERS:
        raise HTTPException(status_code=404, detail=f"Ticker {ticker} not found")
    try:
        return run_regime_backtest(ticker, horizon_days=horizon)
    except Exception as e:
        logger.error(f"Backtest error for {ticker}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
