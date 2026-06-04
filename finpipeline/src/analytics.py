# src/analytics.py
import pandas as pd
from src.db import get_connection


def get_price_history(ticker: str, start_date: str, end_date: str) -> list[dict]:
    """Returns OHLCV data for a ticker within a date range."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT date, open, high, low, close, volume
        FROM stock_prices
        WHERE ticker = %s AND date BETWEEN %s AND %s
        ORDER BY date ASC
    """, (ticker, start_date, end_date))

    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    return [
        {
            'date': str(row[0]),
            'open': float(row[1]),
            'high': float(row[2]),
            'low': float(row[3]),
            'close': float(row[4]),
            'volume': int(row[5])
        }
        for row in rows
    ]


def get_rolling_average(ticker: str, window: int = 30) -> list[dict]:
    """Returns closing price with rolling average overlay."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            date,
            close,
            AVG(close) OVER (
                ORDER BY date
                ROWS BETWEEN %s PRECEDING AND CURRENT ROW
            ) as rolling_avg
        FROM stock_prices
        WHERE ticker = %s
        ORDER BY date ASC
    """, (window - 1, ticker))

    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    return [
        {
            'date': str(row[0]),
            'close': float(row[1]),
            'rolling_avg': round(float(row[2]), 2)
        }
        for row in rows
    ]


def get_volatility(ticker: str, days: int = 30) -> dict:
    """
    Calculates annualized volatility for a ticker over last N days.
    Volatility = std dev of daily returns * sqrt(252)
    252 = trading days in a year
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT date, close
        FROM stock_prices
        WHERE ticker = %s
        ORDER BY date DESC
        LIMIT %s
    """, (ticker, days))

    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    if len(rows) < 2:
        return {'ticker': ticker, 'volatility': None, 'error': 'insufficient data'}

    df = pd.DataFrame(rows, columns=['date', 'close'])
    df['close'] = df['close'].astype(float)
    df = df.sort_values('date')
    df['daily_return'] = df['close'].pct_change()

    volatility = df['daily_return'].std() * (252 ** 0.5) * 100  # as percentage

    return {
        'ticker': ticker,
        'days': days,
        'volatility_pct': round(float(volatility), 2),
        'data_points': len(rows)
    }


def get_indicator_history(indicator: str, start_date: str, end_date: str) -> list[dict]:
    """Returns economic indicator values for a date range."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT date, value
        FROM economic_indicators
        WHERE indicator = %s AND date BETWEEN %s AND %s
        ORDER BY date ASC
    """, (indicator, start_date, end_date))

    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    return [{'date': str(row[0]), 'value': float(row[1])} for row in rows]


def get_market_summary(tickers: list[str]) -> list[dict]:
    """Returns latest price + 30d change % for a list of tickers."""
    conn = get_connection()
    cursor = conn.cursor()

    results = []
    for ticker in tickers:
        cursor.execute("""
            SELECT date, close
            FROM stock_prices
            WHERE ticker = %s
            ORDER BY date DESC
            LIMIT 31
        """, (ticker,))
        rows = cursor.fetchall()

        if len(rows) < 2:
            continue

        latest_price = float(rows[0][1])
        month_ago_price = float(rows[-1][1])
        change_pct = ((latest_price - month_ago_price) / month_ago_price) * 100

        results.append({
            'ticker': ticker,
            'latest_price': latest_price,
            'latest_date': str(rows[0][0]),
            '30d_change_pct': round(change_pct, 2)
        })

    cursor.close()
    conn.close()
    return results


if __name__ == "__main__":
    print("=== Price History (AAPL, first 3 rows) ===")
    history = get_price_history('AAPL', '2024-01-01', '2024-06-01')
    for row in history[:3]:
        print(row)

    print("\n=== Rolling Average (AAPL, last 3 rows) ===")
    rolling = get_rolling_average('AAPL', window=30)
    for row in rolling[-3:]:
        print(row)

    print("\n=== Volatility ===")
    for ticker in ['AAPL', 'TSLA', 'GOOGL']:
        print(get_volatility(ticker, days=90))

    print("\n=== Market Summary ===")
    summary = get_market_summary(['AAPL', 'GOOGL', 'MSFT', 'TSLA'])
    for s in summary:
        print(s)

    print("\n=== Fed Funds Rate (last 5) ===")
    rates = get_indicator_history('FEDFUNDS', '2023-01-01', '2024-06-01')
    for r in rates[-5:]:
        print(r)
