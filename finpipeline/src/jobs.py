"""Command-line entrypoints for jobs that must run independently of the web service."""
import argparse
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import sys
import time

from src.fetchers.macro_fetcher import fetch_and_store_indicators
from src.fetchers.stock_fetcher import fetch_and_store_stocks


from src.instruments import list_instruments
from src.db import get_connection


def run_market(market: str = "india", backfill: bool = False) -> dict:
    instruments = list_instruments(market)
    timezone_name = "Asia/Kolkata" if market == "india" else "America/New_York"
    end = datetime.now(ZoneInfo(timezone_name)).date() + timedelta(days=1)
    start = end - timedelta(days=365 * 5 if backfill else 10)
    return fetch_and_store_stocks(
        [item["ticker"] for item in instruments], str(start), str(end),
        job_name=f"market-{market}{'-backfill' if backfill else ''}",
        timezones={item["ticker"]: item["timezone"] for item in instruments},
    )


def run_macro(market: str | None = None, backfill: bool = False) -> dict:
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=365 * 10 if backfill else 90)
    return fetch_and_store_indicators(
        str(start), str(end),
        job_name=f"macro-{market or 'all'}{'-backfill' if backfill else ''}",
        market=market,
    )


def run_news() -> dict:
    try:
        from src.news import fetch_and_store_news
    except ImportError as error:
        raise RuntimeError("News ingestion is not installed yet") from error
    return fetch_and_store_news()


def run_regime() -> dict:
    from src.regime_v2 import store_india_fingerprints
    conn = get_connection(); cursor = conn.cursor()
    started = datetime.now(timezone.utc); clock = time.monotonic()
    cursor.execute("""
        INSERT INTO pipeline_runs (source, job_name, status, started_at)
        VALUES ('derived', 'regime-india-us-v1', 'running', %s) RETURNING id
    """, (started,))
    run_id = cursor.fetchone()[0]; conn.commit()
    try:
        result = store_india_fingerprints()
    except Exception as error:
        result = {"total_inserted": 0, "errors": [str(error)]}
    errors = result.get("errors", [])
    cursor.execute("""
        UPDATE pipeline_runs SET status=%s, records_fetched=%s, error_message=%s,
            completed_at=%s, duration_ms=%s WHERE id=%s
    """, ('failed' if errors else 'success', result.get('total_inserted', 0),
          '\n'.join(errors) or None, datetime.now(timezone.utc),
          round((time.monotonic() - clock) * 1000), run_id))
    conn.commit(); cursor.close(); conn.close()
    result["run_id"] = run_id
    return result


JOBS = {"market": run_market, "macro": run_macro, "news": run_news, "regime": run_regime}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run one FinPipeline job and exit")
    parser.add_argument("command", choices=["run"])
    parser.add_argument("job", choices=sorted(JOBS))
    parser.add_argument("--market", choices=["india", "global"])
    parser.add_argument("--backfill", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.job == "market":
            result = run_market(args.market or "india", args.backfill)
        elif args.job == "macro":
            result = run_macro(args.market, args.backfill)
        else:
            result = JOBS[args.job]()
    except Exception as error:
        print(f"{args.job} job failed: {error}", file=sys.stderr)
        return 1
    errors = result.get("errors", [])
    print(f"{args.job} job wrote {result.get('total_inserted', 0)} rows")
    if errors:
        print("\n".join(str(error) for error in errors), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
