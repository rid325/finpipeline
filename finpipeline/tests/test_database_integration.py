import os

import pandas as pd
import psycopg2
import pytest

from src.fetchers import stock_fetcher


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="integration database not configured")
def test_market_ingestion_is_idempotent_and_accepts_long_symbols(monkeypatch):
    database_url = os.environ["TEST_DATABASE_URL"]
    frame = pd.DataFrame(
        {
            "Open": [10.0], "High": [12.0], "Low": [9.0], "Close": [11.0],
            "Adj Close": [11.0], "Volume": [100],
        },
        index=pd.DatetimeIndex(["2026-10-16"], name="Date"),
    )

    class FakeTicker:
        def __init__(self, ticker):
            self.ticker = ticker

        def history(self, **kwargs):
            return frame.copy()

    monkeypatch.setattr(stock_fetcher.yf, "Ticker", FakeTicker)
    monkeypatch.setattr(stock_fetcher, "get_connection", lambda: psycopg2.connect(database_url))

    for _ in range(2):
        result = stock_fetcher.fetch_and_store_stocks(
            ["BHARTIARTL.NS"], "2026-10-16", "2026-10-17",
            job_name="test-market-idempotency",
            timezones={"BHARTIARTL.NS": "Asia/Kolkata"},
        )
        assert result["errors"] == []

    conn = psycopg2.connect(database_url)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM stock_prices WHERE ticker='BHARTIARTL.NS' AND date='2026-10-16'")
    assert cursor.fetchone()[0] == 1
    cursor.execute("DELETE FROM stock_prices WHERE ticker='BHARTIARTL.NS' AND date='2026-10-16'")
    cursor.execute("DELETE FROM pipeline_runs WHERE job_name='test-market-idempotency'")
    conn.commit()
    cursor.close()
    conn.close()
