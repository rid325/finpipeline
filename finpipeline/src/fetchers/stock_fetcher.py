# src/fetchers/stock_fetcher.py
import yfinance as yf
import pandas as pd
import requests
import time
from datetime import datetime, timezone
from src.db import get_connection


def fetch_yahoo_chart_history(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Fetch OHLCV data directly from Yahoo's chart endpoint as a yfinance fallback."""
    start = int(datetime.strptime(start_date, '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp())
    end = int(datetime.strptime(end_date, '%Y-%m-%d').replace(tzinfo=timezone.utc).timestamp())
    response = requests.get(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
        params={'period1': start, 'period2': end, 'interval': '1d', 'events': 'history'},
        headers={'User-Agent': 'Mozilla/5.0'},
        timeout=20
    )
    response.raise_for_status()
    result = response.json()['chart']['result'][0]
    timestamps = result.get('timestamp', [])
    quote = result['indicators']['quote'][0]
    rows = []
    for index, timestamp in enumerate(timestamps):
        values = {field: quote[field][index] for field in ('open', 'high', 'low', 'close', 'volume')}
        if any(value is None for value in values.values()):
            continue
        rows.append({
            'date': datetime.fromtimestamp(timestamp, tz=timezone.utc).date(),
            **values
        })
    return pd.DataFrame(rows)


def fetch_and_store_stocks(
    tickers: list[str], start_date: str, end_date: str, job_name: str = "market-global"
) -> dict:
    """
    Fetches OHLCV data for given tickers and stores in postgres.
    Returns a summary of what happened.
    """
    conn = get_connection()
    cursor = conn.cursor()

    # log that pipeline started
    started_at = datetime.now(timezone.utc)
    started_clock = time.monotonic()
    cursor.execute("""
        INSERT INTO pipeline_runs (source, job_name, status, started_at)
        VALUES (%s, %s, %s, %s)
        RETURNING id
    """, ('yahoo_finance', job_name, 'running', started_at))
    run_id = cursor.fetchone()[0]
    conn.commit()

    total_inserted = 0
    errors = []

    for ticker in tickers:
        try:
            print(f"Fetching {ticker}...")

            # Prefer yfinance, but fall back to Yahoo's chart endpoint when its
            # cookie/crumb flow is rate-limited on hosted infrastructure.
            try:
                stock = yf.Ticker(ticker)
                df = stock.history(start=start_date, end=end_date)
            except Exception as primary_error:
                print(f"  yfinance failed for {ticker}: {primary_error}; trying chart endpoint")
                df = fetch_yahoo_chart_history(ticker, start_date, end_date)

            if df.empty:
                print(f"  yfinance returned no data for {ticker}; trying chart endpoint")
                df = fetch_yahoo_chart_history(ticker, start_date, end_date)
                if df.empty:
                    errors.append(f"{ticker}: no data returned")
                    continue

            # clean the dataframe
            df = df.reset_index()
            df.columns = [c.lower() for c in df.columns]
            df['ticker'] = ticker
            df['date'] = pd.to_datetime(df['date'], utc=True).dt.date

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
            completed_at = %s,
            duration_ms = %s
        WHERE id = %s
    """, (
        'failed' if errors else 'success',
        total_inserted,
        '\n'.join(errors) if errors else None,
        datetime.now(timezone.utc),
        round((time.monotonic() - started_clock) * 1000),
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
