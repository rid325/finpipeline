# src/api.py
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import time
import logging

from src.analytics import (
    get_price_history,
    get_rolling_average,
    get_volatility,
    get_indicator_history,
    get_market_summary
)
from src.db import get_connection

# set up structured logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)

# valid tickers and indicators your API supports
VALID_TICKERS = {'AAPL', 'GOOGL', 'MSFT', 'TSLA'}
VALID_INDICATORS = {'CPI', 'FEDFUNDS', 'UNRATE', 'GDP', 'T10Y2Y'}


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting finpipeline API")
    yield
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