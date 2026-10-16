"""Command-line entrypoints for jobs that must run independently of the web service."""
import argparse
from datetime import datetime, timedelta, timezone
import sys

from src.fetchers.macro_fetcher import fetch_and_store_indicators
from src.fetchers.stock_fetcher import fetch_and_store_stocks


GLOBAL_TICKERS = ["AAPL", "GOOGL", "MSFT", "TSLA"]


def run_market() -> dict:
    end = datetime.now(timezone.utc).date() + timedelta(days=1)
    start = end - timedelta(days=10)
    return fetch_and_store_stocks(
        GLOBAL_TICKERS, str(start), str(end), job_name="market-global"
    )


def run_macro() -> dict:
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=90)
    return fetch_and_store_indicators(str(start), str(end), job_name="macro-us")


def run_news() -> dict:
    try:
        from src.news import fetch_and_store_news
    except ImportError as error:
        raise RuntimeError("News ingestion is not installed yet") from error
    return fetch_and_store_news()


JOBS = {"market": run_market, "macro": run_macro, "news": run_news}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run one FinPipeline job and exit")
    parser.add_argument("command", choices=["run"])
    parser.add_argument("job", choices=sorted(JOBS))
    args = parser.parse_args(argv)
    try:
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
