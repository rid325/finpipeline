# src/fetchers/stock_fetcher.py
import yfinance as yf
import pandas as pd
import requests
import time
from psycopg2.extras import execute_values
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
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
    exchange_timezone = result.get('meta', {}).get('exchangeTimezoneName', 'UTC')
    timestamps = result.get('timestamp', [])
    quote = result['indicators']['quote'][0]
    adjusted = result.get('indicators', {}).get('adjclose', [{}])[0].get('adjclose', [])
    rows = []
    for index, timestamp in enumerate(timestamps):
        values = {field: quote[field][index] for field in ('open', 'high', 'low', 'close', 'volume')}
        if any(values[field] is None for field in ('open', 'high', 'low', 'close')):
            continue
        rows.append({
            'date': datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone(
                ZoneInfo(exchange_timezone)
            ).date(),
            'adj close': adjusted[index] if index < len(adjusted) else values['close'],
            **values
        })
    return pd.DataFrame(rows)


def normalize_yahoo_history(df: pd.DataFrame, ticker: str, timezone_name: str) -> pd.DataFrame:
    """Normalize Yahoo bars while preserving the exchange-local session date."""
    frame = df.reset_index().copy()
    frame.columns = [str(column).lower().replace('_', ' ') for column in frame.columns]
    date_column = 'date' if 'date' in frame.columns else frame.columns[0]
    dates = pd.to_datetime(frame[date_column])
    if getattr(dates.dt, 'tz', None) is not None:
        dates = dates.dt.tz_convert(timezone_name)
    frame['date'] = dates.dt.date
    frame['ticker'] = ticker
    if 'adj close' not in frame.columns:
        frame['adj close'] = frame['close']
    frame['adj close'] = frame['adj close'].fillna(frame['close'])
    return frame


def fetch_and_store_stocks(
    tickers: list[str], start_date: str, end_date: str, job_name: str = "market-global",
    timezones: dict[str, str] | None = None,
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
                df = stock.history(
                    start=start_date, end=end_date, auto_adjust=False, actions=False
                )
            except Exception as primary_error:
                print(f"  yfinance failed for {ticker}: {primary_error}; trying chart endpoint")
                df = fetch_yahoo_chart_history(ticker, start_date, end_date)

            if df.empty:
                print(f"  yfinance returned no data for {ticker}; trying chart endpoint")
                df = fetch_yahoo_chart_history(ticker, start_date, end_date)
                if df.empty:
                    errors.append(f"{ticker}: no data returned")
                    continue

            df = normalize_yahoo_history(
                df, ticker, (timezones or {}).get(ticker, 'UTC')
            )

            rows = []
            for _, row in df.iterrows():
                prices = [float(row[name]) for name in ('open', 'high', 'low', 'close')]
                if not all(pd.notna(value) and value >= 0 for value in prices):
                    raise ValueError(f"invalid OHLC values on {row['date']}")
                volume = None if pd.isna(row.get('volume')) else int(row['volume'])
                rows.append((
                    row['ticker'], row['date'], *prices,
                    float(row['adj close']), volume
                ))

            execute_values(cursor, """
                INSERT INTO stock_prices
                    (ticker, date, open, high, low, close, adjusted_close, volume)
                VALUES %s
                ON CONFLICT ON CONSTRAINT uq_ticker_date DO UPDATE SET
                    open = EXCLUDED.open, high = EXCLUDED.high,
                    low = EXCLUDED.low, close = EXCLUDED.close,
                    adjusted_close = EXCLUDED.adjusted_close,
                    volume = EXCLUDED.volume, updated_at = NOW()
            """, rows, page_size=500)
            total_inserted += len(rows)

            conn.commit()
            print(f"  {ticker}: {len(df)} rows processed")

        except Exception as e:
            conn.rollback()
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
