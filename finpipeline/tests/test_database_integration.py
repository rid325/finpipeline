import os

import psycopg2
import pytest


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="integration database not configured")
def test_market_upsert_is_idempotent_and_accepts_long_symbols():
    conn = psycopg2.connect(os.environ["TEST_DATABASE_URL"])
    cursor = conn.cursor()
    statement = """
        INSERT INTO stock_prices
            (ticker, date, open, high, low, close, adjusted_close, volume)
        VALUES ('BHARTIARTL.NS', '2026-10-16', 10, 12, 9, 11, 11, 100)
        ON CONFLICT ON CONSTRAINT uq_ticker_date DO UPDATE SET
            close=EXCLUDED.close, adjusted_close=EXCLUDED.adjusted_close,
            updated_at=NOW()
    """
    cursor.execute(statement)
    cursor.execute(statement)
    cursor.execute("SELECT COUNT(*) FROM stock_prices WHERE ticker='BHARTIARTL.NS' AND date='2026-10-16'")
    assert cursor.fetchone()[0] == 1
    conn.rollback()
    cursor.close()
    conn.close()
