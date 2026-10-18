# src/fetchers/macro_fetcher.py
import requests
import pandas as pd
from psycopg2.extras import execute_values
from io import StringIO
from datetime import datetime, timezone
import time
import csv
from pathlib import Path
from src.db import get_connection
from src.config import FRED_API_KEY
from src.instruments import list_macro_series

CURATED_REPO_CSV = Path(__file__).resolve().parents[2] / "data" / "rbi_policy_repo_rate.csv"


def fetch_fred_series(series_id: str, start_date: str, end_date: str) -> list:
    """Fetch a single series from FRED API. Returns list of (date, value) tuples."""
    if not FRED_API_KEY:
        response = requests.get(
            "https://fred.stlouisfed.org/graph/fredgraph.csv",
            params={'id': series_id, 'cosd': start_date, 'coed': end_date},
            timeout=20
        )
        response.raise_for_status()
        frame = pd.read_csv(StringIO(response.text))
        value_column = series_id if series_id in frame.columns else frame.columns[-1]
        frame[value_column] = pd.to_numeric(frame[value_column], errors='coerce')
        return [
            (str(row['observation_date']), float(row[value_column]))
            for _, row in frame.dropna(subset=[value_column]).iterrows()
        ]

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


def load_curated_repo_rows() -> list[tuple[str, float]]:
    with CURATED_REPO_CSV.open(newline="", encoding="utf-8") as handle:
        return [(row["date"], float(row["value"])) for row in csv.DictReader(handle)]


def fetch_and_store_indicators(
    start_date: str, end_date: str, job_name: str = "macro-all",
    market: str | None = None,
) -> dict:
    conn = get_connection()
    cursor = conn.cursor()

    started_at = datetime.now(timezone.utc)
    started_clock = time.monotonic()
    cursor.execute("""
        INSERT INTO pipeline_runs (source, job_name, status, started_at)
        VALUES (%s, %s, %s, %s)
        RETURNING id
    """, ('fred', job_name, 'running', started_at))
    run_id = cursor.fetchone()[0]
    conn.commit()

    total_inserted = 0
    errors = []

    series_registry = list_macro_series(market)
    for series in series_registry:
        name = series["indicator"]
        series_id = series["series_id"]
        try:
            print(f"Fetching {name} ({series_id})...")
            observations = (
                load_curated_repo_rows()
                if series["manually_curated"]
                else fetch_fred_series(series_id, start_date, end_date)
            )

            rows = []
            for date_str, value in observations:
                if not validate_indicator_row(name, date_str, value):
                    errors.append(f"{name} {date_str}: failed validation (value={value})")
                    continue
                rows.append((
                    name, date_str, value, series_id, series["market"],
                    series["source"], series["manually_curated"]
                ))

            if rows:
                execute_values(cursor, """
                    INSERT INTO economic_indicators
                        (indicator, date, value, series_id, market, source, manually_curated)
                    VALUES %s
                    ON CONFLICT ON CONSTRAINT uq_indicator_date DO UPDATE SET
                        value = EXCLUDED.value, series_id = EXCLUDED.series_id,
                        market = EXCLUDED.market, source = EXCLUDED.source,
                        manually_curated = EXCLUDED.manually_curated, updated_at = NOW()
                """, rows, page_size=500)
                total_inserted += len(rows)

            conn.commit()
            print(f"  {name}: {len(observations)} observations stored")

        except Exception as e:
            conn.rollback()
            errors.append(f"{name}: {e}")

    cursor.execute("""
        UPDATE pipeline_runs
        SET status = %s, records_fetched = %s,
            error_message = %s, completed_at = %s, duration_ms = %s
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

    return {'run_id': run_id, 'total_inserted': total_inserted, 'errors': errors}


if __name__ == "__main__":
    result = fetch_and_store_indicators('2020-01-01', '2024-06-01')
    print(f"\nMacro pipeline complete:")
    print(f"  Records inserted: {result['total_inserted']}")
    print(f"  Errors: {result['errors'] or 'none'}")
