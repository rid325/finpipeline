"""India-aware historical analogy engine with expanding, no-lookahead scaling."""
from __future__ import annotations

from datetime import datetime, timezone
import math

import numpy as np
import pandas as pd
from psycopg2.extras import Json

from src.db import get_connection


METHOD_VERSION = "india-us-v1"
MIN_HISTORY_MONTHS = 24
FEATURES = [
    "nifty_return_63d_pct", "nifty_vol_21d_ann_pct", "india_vix_level",
    "usdinr_change_21d_pct", "brent_change_21d_pct", "us_cpi_yoy_pct",
    "fedfunds_level", "unrate_level", "us_gdp_yoy_pct", "t10y2y_level",
]
CAVEAT = (
    "Historical similarity is descriptive, not a forecast or investment advice. "
    "Macro observations use current FRED values keyed by observation date; revisions "
    "and publication lags mean historical results are not a true real-time vintage backtest."
)


def expanding_zscores(frame: pd.DataFrame, min_periods: int = MIN_HISTORY_MONTHS) -> pd.DataFrame:
    """Z-score each row using only values available through that row."""
    means = frame.expanding(min_periods=min_periods).mean()
    standard_deviations = frame.expanding(min_periods=min_periods).std(ddof=1).replace(0, np.nan)
    return ((frame - means) / standard_deviations).clip(-4, 4)


def _series(frame: pd.DataFrame) -> pd.Series:
    data = frame.copy()
    data["date"] = pd.to_datetime(data["date"])
    return data.sort_values("date").set_index("date")["value"].astype(float)


def build_raw_monthly_features(
    markets: dict[str, pd.DataFrame], macro: dict[str, pd.DataFrame]
) -> tuple[pd.DataFrame, pd.Series]:
    nifty = _series(markets["^NSEI"])
    vix = _series(markets["^INDIAVIX"])
    usdinr = _series(markets["USDINR=X"])
    brent = _series(markets["BZ=F"])
    daily = pd.DataFrame(index=nifty.index)
    daily["nifty_return_63d_pct"] = nifty.pct_change(63, fill_method=None) * 100
    daily["nifty_vol_21d_ann_pct"] = nifty.pct_change(fill_method=None).rolling(21).std(ddof=1) * math.sqrt(252) * 100
    daily["india_vix_level"] = vix.reindex(daily.index, method="ffill")
    daily["usdinr_change_21d_pct"] = usdinr.pct_change(21, fill_method=None).reindex(daily.index, method="ffill") * 100
    daily["brent_change_21d_pct"] = brent.pct_change(21, fill_method=None).reindex(daily.index, method="ffill") * 100
    monthly = daily.groupby(daily.index.to_period("M")).tail(1)

    cpi = _series(macro["CPI"]).pct_change(12, fill_method=None) * 100
    gdp = _series(macro["GDP"]).pct_change(4, fill_method=None) * 100
    macro_features = {
        "us_cpi_yoy_pct": cpi,
        "fedfunds_level": _series(macro["FEDFUNDS"]),
        "unrate_level": _series(macro["UNRATE"]),
        "us_gdp_yoy_pct": gdp,
        "t10y2y_level": _series(macro["T10Y2Y"]),
    }
    for name, values in macro_features.items():
        monthly[name] = values.reindex(monthly.index, method="ffill")
    return monthly[FEATURES], nifty


def rank_similar_periods(zscores: pd.DataFrame, current_date, limit: int = 3) -> list[dict]:
    complete = zscores.dropna()
    current_date = pd.Timestamp(current_date)
    if current_date not in complete.index:
        return []
    current = complete.loc[current_date].to_numpy(dtype=float)
    current_norm = np.linalg.norm(current)
    ranked = []
    for date_value, row in complete[complete.index < current_date].iterrows():
        vector = row.to_numpy(dtype=float)
        denominator = current_norm * np.linalg.norm(vector)
        if not denominator or not np.isfinite(denominator):
            continue
        ranked.append({"date": date_value, "similarity": float(np.dot(current, vector) / denominator)})
    return sorted(ranked, key=lambda item: (item["similarity"], item["date"]), reverse=True)[:limit]


def _forward_returns(nifty: pd.Series, anchor) -> dict[str, float] | None:
    index = nifty.index.get_indexer([pd.Timestamp(anchor)])[0]
    if index < 0 or index + 126 >= len(nifty):
        return None
    start = float(nifty.iloc[index])
    return {
        label: round((float(nifty.iloc[index + sessions]) / start - 1) * 100, 2)
        for label, sessions in (("1m", 21), ("3m", 63), ("6m", 126))
    }


def regime_from_zscore(row: pd.Series) -> tuple[str, float]:
    signs = pd.Series([-1, 1, 1, 1, 1, 1, 1, 1, -1, -1], index=FEATURES)
    stress = float((row * signs).mean())
    label = "contractionary" if stress >= 0.5 else "expansionary" if stress <= -0.5 else "transitional"
    return label, round(stress, 3)


def _load_inputs() -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    conn = get_connection()
    cursor = conn.cursor()
    markets = {}
    for ticker in ("^NSEI", "^INDIAVIX", "USDINR=X", "BZ=F"):
        cursor.execute("SELECT date, COALESCE(adjusted_close, close) FROM stock_prices WHERE ticker=%s ORDER BY date", (ticker,))
        markets[ticker] = pd.DataFrame(cursor.fetchall(), columns=["date", "value"])
    macro = {}
    for indicator in ("CPI", "FEDFUNDS", "UNRATE", "GDP", "T10Y2Y"):
        cursor.execute("SELECT date, value FROM economic_indicators WHERE indicator=%s ORDER BY date", (indicator,))
        macro[indicator] = pd.DataFrame(cursor.fetchall(), columns=["date", "value"])
    cursor.close(); conn.close()
    return markets, macro


def compute_regime_current() -> dict:
    missing = []
    markets, macro = _load_inputs()
    for name, frame in {**markets, **macro}.items():
        if frame.empty:
            missing.append(name)
    if missing:
        return _insufficient(0, missing)
    raw, nifty = build_raw_monthly_features(markets, macro)
    complete_raw = raw.dropna()
    zscores = expanding_zscores(complete_raw)
    complete_z = zscores.dropna()
    if complete_z.empty:
        return _insufficient(len(complete_raw), [])
    current_date = complete_z.index[-1]
    candidates = rank_similar_periods(zscores, current_date, limit=max(3, len(zscores)))
    analogues = []
    for candidate in candidates:
        outcomes = _forward_returns(nifty, candidate["date"])
        if outcomes:
            analogues.append({
                "date": str(candidate["date"].date()),
                "similarity": round(candidate["similarity"], 4),
                "nifty_forward_return_pct": outcomes,
            })
        if len(analogues) == 3:
            break
    if len(analogues) < 3:
        return _insufficient(len(complete_z), ["three historical periods with 126 later sessions"])
    label, stress = regime_from_zscore(complete_z.loc[current_date])
    summaries = {}
    for label_name, sessions in (("1m", 21), ("3m", 63), ("6m", 126)):
        values = [item["nifty_forward_return_pct"][label_name] for item in analogues]
        summaries[label_name] = {
            "trading_sessions": sessions, "sample_size": len(values),
            "median_pct": round(float(np.median(values)), 2),
            "mean_pct": round(float(np.mean(values)), 2),
            "positive_rate_pct": round(sum(value > 0 for value in values) / len(values) * 100, 1),
        }
    return {
        "status": "ok", "method_version": METHOD_VERSION,
        "as_of_date": str(current_date.date()),
        "regime": {"label": label, "stress_z": stress},
        "current": {
            "raw_features": {key: round(float(value), 4) for key, value in complete_raw.loc[current_date].items()},
            "standardized_features": {key: round(float(value), 4) for key, value in complete_z.loc[current_date].items()},
            "history_months": len(complete_z),
        },
        "similar_periods": analogues,
        "nifty_forward_summary": summaries,
        "caveats": [CAVEAT],
    }


def _insufficient(available: int, missing: list[str]) -> dict:
    return {
        "status": "insufficient_history", "method_version": METHOD_VERSION,
        "required_months": MIN_HISTORY_MONTHS, "available_months": available,
        "missing_features": missing,
        "message": "More complete historical observations are required before analogues can be computed.",
        "caveats": [CAVEAT],
    }


def store_india_fingerprints() -> dict:
    markets, macro = _load_inputs()
    if any(frame.empty for frame in list(markets.values()) + list(macro.values())):
        return {"total_inserted": 0, "errors": [], "warnings": ["required regime inputs are missing"]}
    raw, _ = build_raw_monthly_features(markets, macro)
    raw = raw.dropna()
    standardized = expanding_zscores(raw).dropna()
    conn = get_connection(); cursor = conn.cursor(); written = 0
    for date_value, row in standardized.iterrows():
        label, stress = regime_from_zscore(row)
        cursor.execute("""
            INSERT INTO macro_fingerprints
                (date, regime, overall_stress_score, method_version, raw_features,
                 standardized_features, history_count, computed_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (date, method_version) DO UPDATE SET
                regime=EXCLUDED.regime, overall_stress_score=EXCLUDED.overall_stress_score,
                raw_features=EXCLUDED.raw_features,
                standardized_features=EXCLUDED.standardized_features,
                history_count=EXCLUDED.history_count, computed_at=EXCLUDED.computed_at
        """, (date_value.date(), label, stress, METHOD_VERSION,
              Json({key: float(value) for key, value in raw.loc[date_value].items()}),
              Json({key: float(value) for key, value in row.items()}),
              int(raw.index.get_loc(date_value) + 1), datetime.now(timezone.utc)))
        written += cursor.rowcount
    conn.commit(); cursor.close(); conn.close()
    return {"total_inserted": written, "errors": []}
