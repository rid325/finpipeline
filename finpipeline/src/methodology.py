"""Factual methodology and cadence-aware freshness contracts for the UI."""
from datetime import date, datetime, timezone

import pandas as pd

from src.db import get_connection
from src.regime_v2 import CAVEAT, FEATURES, METHOD_VERSION
from src.config import NEWS_FEEDS_ENABLED


DEFAULT_JOB_CADENCE = {
    "expected_cadence": "daily",
    "threshold_unit": "hours",
    "fresh_threshold": 36,
    "delayed_threshold": 72,
}


def _job_cadence(job_name: str) -> dict:
    if job_name.endswith("-backfill") or "bootstrap" in job_name:
        return {
            "expected_cadence": "one-time backfill",
            "threshold_unit": None,
            "fresh_threshold": None,
            "delayed_threshold": None,
        }
    if job_name.startswith("market-"):
        return {
            "expected_cadence": "weekdays after exchange close",
            "threshold_unit": "business_days",
            "fresh_threshold": 1,
            "delayed_threshold": 2,
        }
    if job_name == "news-india":
        return {
            "expected_cadence": "every 4 hours when licensed feeds are enabled",
            "threshold_unit": "hours",
            "fresh_threshold": 6,
            "delayed_threshold": 12,
        }
    if job_name.startswith("macro-") or job_name.startswith("regime-"):
        return DEFAULT_JOB_CADENCE.copy()
    return DEFAULT_JOB_CADENCE.copy()


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def job_freshness(
    job_name: str,
    last_success: datetime | None,
    last_problem: datetime | None,
    now: datetime,
) -> dict:
    """Describe a job against its declared cadence without hiding newer failures."""
    cadence = _job_cadence(job_name)
    last_success = _as_utc(last_success)
    last_problem = _as_utc(last_problem)
    now = _as_utc(now)
    result = {**cadence, "age": None}
    if last_success is None:
        result["status"] = "problem" if last_problem else "never_succeeded"
        return result
    if last_problem and last_problem > last_success:
        result["status"] = "problem"
        return result
    if cadence["expected_cadence"] == "one-time backfill":
        result["status"] = "completed"
        return result
    if cadence["threshold_unit"] == "business_days":
        age = max(len(pd.bdate_range(last_success.date(), now.date())) - 1, 0)
    else:
        age = max((now - last_success).total_seconds() / 3600, 0)
        age = round(age, 1)
    result["age"] = age
    result["status"] = (
        "fresh" if age <= cadence["fresh_threshold"]
        else "delayed" if age <= cadence["delayed_threshold"]
        else "stale"
    )
    return result


def market_freshness(as_of: date | None, today: date) -> str:
    if as_of is None:
        return "never_loaded"
    business_days = max(len(pd.bdate_range(as_of, today)) - 1, 0)
    return "fresh" if business_days <= 1 else "delayed" if business_days <= 2 else "stale"


def age_freshness(as_of: date | None, today: date, frequency: str) -> str:
    if as_of is None:
        return "never_loaded"
    age = (today - as_of).days
    fresh, delayed = {
        "daily": (4, 8), "monthly": (45, 75), "quarterly": (120, 160),
        "event": (365, 730),
    }.get(frequency, (7, 14))
    return "fresh" if age <= fresh else "delayed" if age <= delayed else "stale"


def get_freshness() -> dict:
    conn = get_connection(); cursor = conn.cursor(); now = datetime.now(timezone.utc); today = now.date()
    cursor.execute("""
        SELECT i.ticker, i.market, MAX(p.date)
        FROM instruments i LEFT JOIN stock_prices p ON p.ticker=i.ticker
        WHERE i.active=TRUE GROUP BY i.ticker, i.market ORDER BY i.market, i.ticker
    """)
    instruments = [
        {"ticker": row[0], "market": row[1], "as_of": str(row[2]) if row[2] else None,
         "status": market_freshness(row[2], today), "expected_cadence": "exchange trading days"}
        for row in cursor.fetchall()
    ]
    cursor.execute("""
        SELECT s.indicator, s.market, s.frequency, s.source, s.manually_curated, MAX(e.date)
        FROM macro_series s LEFT JOIN economic_indicators e ON e.indicator=s.indicator
        WHERE s.active=TRUE GROUP BY s.indicator, s.market, s.frequency, s.source, s.manually_curated
        ORDER BY s.market, s.indicator
    """)
    macro = [
        {"indicator": row[0], "market": row[1], "frequency": row[2], "source": row[3],
         "manually_curated": row[4], "as_of": str(row[5]) if row[5] else None,
         "status": age_freshness(row[5], today, row[2])}
        for row in cursor.fetchall()
    ]
    cursor.execute("""
        SELECT job_name, MAX(completed_at) FILTER (WHERE status='success'),
               MAX(completed_at) FILTER (WHERE status IN ('failed','partial'))
        FROM pipeline_runs WHERE job_name IS NOT NULL GROUP BY job_name ORDER BY job_name
    """)
    jobs = []
    for job_name, last_success, last_problem in cursor.fetchall():
        jobs.append({
            "job_name": job_name,
            "last_successful_run": last_success.isoformat() if last_success else None,
            "last_problem_run": last_problem.isoformat() if last_problem else None,
            **job_freshness(job_name, last_success, last_problem, now),
        })
    cursor.execute("SELECT MAX(published_at), COUNT(*) FROM news_articles")
    latest_news, news_count = cursor.fetchone()
    cursor.close(); conn.close()
    return {
        "generated_at": now.isoformat(),
        "instruments": instruments, "macro_series": macro,
        "news": {"configured": bool(NEWS_FEEDS_ENABLED), "article_count": news_count,
                 "as_of": latest_news.isoformat() if latest_news else None,
                 "status": "not_configured" if not NEWS_FEEDS_ENABLED else "never_loaded" if not latest_news else "available"},
        "jobs": jobs,
    }


def get_methodology() -> dict:
    conn = get_connection(); cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM instruments WHERE active=TRUE")
    instrument_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM macro_series WHERE active=TRUE")
    macro_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM stock_prices")
    market_rows = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM economic_indicators")
    macro_rows = cursor.fetchone()[0]
    cursor.close(); conn.close()
    return {
        "live_counts": {
            "active_instruments": instrument_count, "active_macro_series": macro_count,
            "market_observations": market_rows, "macro_observations": macro_rows,
        },
        "sources": [
            {"name": "Yahoo Finance", "data": "daily raw and adjusted OHLCV", "cadence": "after exchange close", "expected_delay": "end-of-day; upstream dependent"},
            {"name": "FRED", "data": "US and India macro observations", "cadence": "daily pull", "expected_delay": "series-specific publication lag and revisions"},
            {"name": "Reserve Bank of India", "data": "manually curated policy repo rate CSV", "cadence": "manual after policy changes", "expected_delay": "until repository CSV is reviewed"},
        ],
        "analytics": {
            "30_session_change": "latest adjusted close / adjusted close 30 stored sessions earlier - 1",
            "annualized_volatility": "sample standard deviation of daily adjusted returns × sqrt(252)",
            "move_day": "absolute adjusted return > 2 × prior trailing 90-session standard deviation",
            "regime": {"method_version": METHOD_VERSION, "features": FEATURES,
                       "scaling": "expanding z-score using only rows through each historical month"},
        },
        "validation": ["finite non-negative OHLC", "natural-key upserts", "missing FRED values removed", "exchange-local session dates", "pipeline run telemetry"],
        "limitations": [
            "Yahoo Finance and FRED are upstream dependencies and may revise observations.",
            "Indian exchange holidays are represented by an absent session, not an inferred row.",
            "News sources are disabled until suitable permission is obtained.",
            CAVEAT,
        ],
        "not_investment_advice": True,
    }
