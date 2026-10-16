"""Database-backed instrument and macro registries."""
from src.db import get_connection


def list_instruments(market: str | None = None) -> list[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    query = """
        SELECT ticker, display_name, market, asset_type, currency, exchange, timezone, sector
        FROM instruments WHERE active = TRUE
    """
    params = []
    if market:
        query += " AND market = %s"
        params.append(market.lower())
    query += " ORDER BY market, asset_type, ticker"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    keys = ("ticker", "display_name", "market", "asset_type", "currency", "exchange", "timezone", "sector")
    return [dict(zip(keys, row)) for row in rows]


def instrument_map(market: str | None = None) -> dict[str, dict]:
    return {item["ticker"]: item for item in list_instruments(market)}


def list_macro_series(market: str | None = None, source: str | None = None) -> list[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    query = """
        SELECT indicator, series_id, market, frequency, source, manually_curated
        FROM macro_series WHERE active = TRUE
    """
    params = []
    if market:
        query += " AND market = %s"
        params.append(market.lower())
    if source:
        query += " AND source = %s"
        params.append(source.lower())
    query += " ORDER BY market, indicator"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    keys = ("indicator", "series_id", "market", "frequency", "source", "manually_curated")
    return [dict(zip(keys, row)) for row in rows]
