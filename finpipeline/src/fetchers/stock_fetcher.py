# src/fetchers/stock_fetcher.py
import yfinance as yf
import pandas as pd
from datetime import datetime
from src.db import get_connection


def fetch_and_store_stocks(tickers: list[str], start_date: str, end_date: str) -> dict:
    """
    Fetches OHLCV data for given tickers and stores in postgres.
    Returns a summary of what happened.
    """
    conn = get_connection()
    cursor = conn.cursor()

    # log that pipeline started
    cursor.execute("""
        INSERT INTO pipeline_runs (source, status, started_at)
        VALUES (%s, %s, %s)
        RETURNING id
    """, ('yahoo_finance', 'running', datetime.now()))
    run_id = cursor.fetchone()[0]
    conn.commit()

    total_inserted = 0
    errors = []

    for ticker in tickers:
        try:
            print(f"Fetching {ticker}...")

            # fetch from yahoo finance
            stock = yf.Ticker(ticker)
            df = stock.history(start=start_date, end=end_date)

            if df.empty:
                errors.append(f"{ticker}: no data returned")
                continue

            # clean the dataframe
            df = df.reset_index()
            df.columns = [c.lower() for c in df.columns]
            df['ticker'] = ticker
            df['date'] = pd.to_datetime(df['date']).dt.date

            # insert each row
            for _, row in df.iterrows():
                try:
                    cursor.execute("""
                        INSERT INTO stock_prices (ticker, date, open, high, low, close, volume)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT ON CONSTRAINT uq_ticker_date DO NOTHING
                    """, (
                        row['ticker'],
                        row['date'],
                        float(row['open']),
                        float(row['high']),
                        float(row['low']),
                        float(row['close']),
                        int(row['volume'])
                    ))
                    total_inserted += cursor.rowcount
                except Exception as e:
                    errors.append(f"{ticker} row {row['date']}: {e}")
                    conn.rollback()

            conn.commit()
            print(f"  {ticker}: {len(df)} rows processed")

        except Exception as e:
            errors.append(f"{ticker}: {e}")

    # update pipeline run as completed
    cursor.execute("""
        UPDATE pipeline_runs
        SET status = %s,
            records_fetched = %s,
            error_message = %s,
            completed_at = %s
        WHERE id = %s
    """, (
        'failed' if errors else 'success',
        total_inserted,
        '\n'.join(errors) if errors else None,
        datetime.now(),
        run_id
    ))
    conn.commit()
    cursor.close()
    conn.close()

    return {
        'run_id': run_id,
        'total_inserted': total_inserted,
        'errors': errors
    }


if __name__ == "__main__":
    result = fetch_and_store_stocks(
        tickers=['AAPL', 'GOOGL', 'MSFT', 'TSLA'],
        start_date='2024-01-01',
        end_date='2024-06-01'
    )
    print(f"\nPipeline complete:")
    print(f"  Records inserted: {result['total_inserted']}")
    print(f"  Errors: {result['errors'] or 'none'}")
