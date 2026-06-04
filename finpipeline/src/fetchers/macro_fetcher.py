# src/fetchers/macro_fetcher.py
import requests
from datetime import datetime
from src.db import get_connection
from src.config import FRED_API_KEY

# these are real FRED series IDs
INDICATORS = {
    'CPI': 'CPIAUCSL',           # consumer price index
    'FEDFUNDS': 'FEDFUNDS',      # federal funds rate
    'UNRATE': 'UNRATE',          # unemployment rate
    'GDP': 'GDP',                # gross domestic product
    'T10Y2Y': 'T10Y2Y'          # 10yr-2yr treasury spread (recession indicator)
}


def fetch_fred_series(series_id: str, start_date: str, end_date: str) -> list:
    """Fetch a single series from FRED API. Returns list of (date, value) tuples."""
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        'series_id': series_id,
        'api_key': FRED_API_KEY,
        'file_type': 'json',
        'observation_start': start_date,
        'observation_end': end_date
    }

    response = requests.get(url, params=params, timeout=10)

    # always check status code — never assume an API call succeeded
    if response.status_code != 200:
        raise Exception(f"FRED API returned {response.status_code}: {response.text}")

    data = response.json()
    observations = data.get('observations', [])

    # FRED uses '.' for missing values — filter those out
    return [
        (obs['date'], float(obs['value']))
        for obs in observations
        if obs['value'] != '.'
    ]


def validate_indicator_row(indicator: str, date_str: str, value: float) -> bool:
    """Basic sanity checks — catch obviously bad data before it hits the DB."""
    if value is None:
        return False
    # unemployment rate should be between 0-100
    if indicator == 'UNRATE' and not (0 <= value <= 100):
        return False
    # interest rate shouldn't be wildly negative
    if indicator == 'FEDFUNDS' and value < -5:
        return False
    return True


def fetch_and_store_indicators(start_date: str, end_date: str) -> dict:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO pipeline_runs (source, status, started_at)
        VALUES (%s, %s, %s)
        RETURNING id
    """, ('fred', 'running', datetime.now()))
    run_id = cursor.fetchone()[0]
    conn.commit()

    total_inserted = 0
    errors = []

    for name, series_id in INDICATORS.items():
        try:
            print(f"Fetching {name} ({series_id})...")
            observations = fetch_fred_series(series_id, start_date, end_date)

            for date_str, value in observations:
                if not validate_indicator_row(name, date_str, value):
                    errors.append(f"{name} {date_str}: failed validation (value={value})")
                    continue

                try:
                    cursor.execute("""
                        INSERT INTO economic_indicators (indicator, date, value)
                        VALUES (%s, %s, %s)
                        ON CONFLICT ON CONSTRAINT uq_indicator_date DO NOTHING
                    """, (name, date_str, value))
                    total_inserted += cursor.rowcount
                except Exception as e:
                    errors.append(f"{name} {date_str}: {e}")
                    conn.rollback()

            conn.commit()
            print(f"  {name}: {len(observations)} observations stored")

        except Exception as e:
            errors.append(f"{name}: {e}")

    cursor.execute("""
        UPDATE pipeline_runs
        SET status = %s, records_fetched = %s,
            error_message = %s, completed_at = %s
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

    return {'run_id': run_id, 'total_inserted': total_inserted, 'errors': errors}


if __name__ == "__main__":
    result = fetch_and_store_indicators('2020-01-01', '2024-06-01')
    print(f"\nMacro pipeline complete:")
    print(f"  Records inserted: {result['total_inserted']}")
    print(f"  Errors: {result['errors'] or 'none'}")
