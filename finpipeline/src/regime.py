# src/regime.py
import pandas as pd
import numpy as np
from src.db import get_connection

# ── indicator metadata ───────────────────────────────────────────────────────
INDICATOR_META = {
    'CPI':      {'label': 'Inflation',       'direction': 'higher_is_worse'},
    'FEDFUNDS': {'label': 'Interest Rates',  'direction': 'higher_is_worse'},
    'UNRATE':   {'label': 'Unemployment',    'direction': 'higher_is_worse'},
    'GDP':      {'label': 'GDP Growth',      'direction': 'higher_is_better'},
    'T10Y2Y':   {'label': 'Yield Curve',     'direction': 'higher_is_better'},
}


def load_indicator_series(indicator: str) -> pd.DataFrame:
    """Load full history of an indicator from the database."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT date, value
        FROM economic_indicators
        WHERE indicator = %s
        ORDER BY date ASC
    """, (indicator,))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    df = pd.DataFrame(rows, columns=['date', 'value'])
    df['date'] = pd.to_datetime(df['date'])
    df['value'] = df['value'].astype(float)
    return df


def compute_percentile_score(series: pd.Series, current_value: float) -> float:
    """Where does current_value sit in the distribution of the series? Returns 0-100."""
    return float((series < current_value).mean() * 100)


def compute_trend(series: pd.Series, window: int = 3) -> str:
    """Is this indicator rising, falling, or stable over last N periods?"""
    if len(series) < window * 2:
        return 'insufficient_data'

    recent = series.iloc[-window:].mean()
    prior = series.iloc[-window*2:-window].mean()
    pct_change = (recent - prior) / abs(prior) * 100

    if pct_change > 2:
        return 'rising'
    elif pct_change < -2:
        return 'falling'
    else:
        return 'stable'


def get_macro_fingerprint(as_of_date: str = None) -> dict:
    """Compute the macro fingerprint for a given date."""
    results = {}
    fingerprint_vector = []

    for indicator, meta in INDICATOR_META.items():
        df = load_indicator_series(indicator)

        if df.empty:
            continue

        if as_of_date:
            cutoff = pd.to_datetime(as_of_date)
            df = df[df['date'] <= cutoff]

        if df.empty:
            continue

        current_value = float(df['value'].iloc[-1])
        current_date = str(df['date'].iloc[-1].date())
        percentile = compute_percentile_score(df['value'], current_value)
        trend = compute_trend(df['value'])

        if meta['direction'] == 'higher_is_worse':
            if percentile >= 75:
                stress_level = 'high'
            elif percentile >= 40:
                stress_level = 'moderate'
            else:
                stress_level = 'low'
        elif meta['direction'] == 'higher_is_better':
            if percentile >= 60:
                stress_level = 'low'
            elif percentile >= 25:
                stress_level = 'moderate'
            else:
                stress_level = 'high'
        else:
            stress_level = 'neutral'

        results[indicator] = {
            'label': meta['label'],
            'current_value': current_value,
            'current_date': current_date,
            'percentile': round(percentile, 1),
            'trend': trend,
            'stress_level': stress_level,
            'direction': meta['direction']
        }

        fingerprint_vector.append(percentile)

    overall_stress = float(np.mean([
        v['percentile'] if INDICATOR_META[k]['direction'] == 'higher_is_worse'
        else (100 - v['percentile'])
        for k, v in results.items()
    ]))

    if overall_stress >= 65:
        regime_label = 'contractionary'
        regime_description = 'High macro stress — elevated inflation, tight rates, or rising unemployment'
    elif overall_stress >= 40:
        regime_label = 'transitional'
        regime_description = 'Mixed signals — some stress indicators elevated, others benign'
    else:
        regime_label = 'expansionary'
        regime_description = 'Low macro stress — favorable conditions for risk assets'

    return {
        'as_of_date': as_of_date or 'latest',
        'regime': regime_label,
        'regime_description': regime_description,
        'overall_stress_score': round(overall_stress, 1),
        'indicators': results,
        'fingerprint_vector': [round(x, 2) for x in fingerprint_vector]
    }


def build_historical_fingerprints() -> pd.DataFrame:
    """Build fingerprints for every month in our history."""
    df_cpi = load_indicator_series('CPI')
    dates = df_cpi['date'].tolist()

    records = []
    for dt in dates:
        date_str = str(dt.date())
        fp = get_macro_fingerprint(as_of_date=date_str)

        if not fp['indicators']:
            continue

        row = {'date': date_str, 'regime': fp['regime'],
               'overall_stress_score': fp['overall_stress_score']}
        for indicator in INDICATOR_META:
            if indicator in fp['indicators']:
                row[f'{indicator}_percentile'] = fp['indicators'][indicator]['percentile']

        records.append(row)

    return pd.DataFrame(records)


def store_fingerprints():
    """Build and store all historical fingerprints in the database."""
    df = build_historical_fingerprints()
    conn = get_connection()
    cursor = conn.cursor()

    inserted = 0
    for _, row in df.iterrows():
        try:
            cursor.execute("""
                INSERT INTO macro_fingerprints
                    (date, regime, overall_stress_score,
                     cpi_percentile, fedfunds_percentile,
                     unrate_percentile, gdp_percentile, t10y2y_percentile)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (date) DO UPDATE SET
                    regime = EXCLUDED.regime,
                    overall_stress_score = EXCLUDED.overall_stress_score,
                    cpi_percentile = EXCLUDED.cpi_percentile,
                    fedfunds_percentile = EXCLUDED.fedfunds_percentile,
                    unrate_percentile = EXCLUDED.unrate_percentile,
                    gdp_percentile = EXCLUDED.gdp_percentile,
                    t10y2y_percentile = EXCLUDED.t10y2y_percentile
            """, (
                row['date'], row['regime'], row.get('overall_stress_score'),
                row.get('CPI_percentile'), row.get('FEDFUNDS_percentile'),
                row.get('UNRATE_percentile'), row.get('GDP_percentile'),
                row.get('T10Y2Y_percentile')
            ))
            inserted += 1
        except Exception as e:
            print(f"Error inserting {row['date']}: {e}")
            conn.rollback()

    conn.commit()
    cursor.close()
    conn.close()
    print(f"Stored {inserted} fingerprints")


if __name__ == "__main__":
    print("=== Current Macro Fingerprint ===")
    fp = get_macro_fingerprint()
    print(f"Regime: {fp['regime'].upper()} (stress score: {fp['overall_stress_score']})")
    print(f"Description: {fp['regime_description']}")
    print()
    for indicator, data in fp['indicators'].items():
        print(f"  {data['label']:<20} {data['current_value']:>8.2f}  "
              f"p{data['percentile']:>5.1f}  "
              f"{data['trend']:<12}  stress={data['stress_level']}")
    print()
    print(f"Fingerprint vector: {fp['fingerprint_vector']}")
