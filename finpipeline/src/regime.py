# src/regime.py
import pandas as pd
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
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


def get_similar_periods(n: int = 10, as_of_date: str = None) -> list[dict]:
    """Find the N most similar historical macro environments to today."""
    current_fp = get_macro_fingerprint(as_of_date=as_of_date)
    current_vector = np.array(current_fp['fingerprint_vector']).reshape(1, -1)

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT date, regime, overall_stress_score,
               cpi_percentile, fedfunds_percentile,
               unrate_percentile, gdp_percentile, t10y2y_percentile
        FROM macro_fingerprints
        ORDER BY date ASC
    """)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    if not rows:
        return []

    df = pd.DataFrame(rows, columns=[
        'date', 'regime', 'overall_stress_score',
        'CPI', 'FEDFUNDS', 'UNRATE', 'GDP', 'T10Y2Y'
    ])

    if as_of_date:
        cutoff = pd.to_datetime(as_of_date)
        df = df[pd.to_datetime(df['date']) < cutoff]
    else:
        df = df.iloc[:-1]

    feature_cols = ['CPI', 'FEDFUNDS', 'UNRATE', 'GDP', 'T10Y2Y']
    df = df.dropna(subset=feature_cols)
    historical_matrix = df[feature_cols].values.astype(float)

    similarities = cosine_similarity(current_vector, historical_matrix)[0]
    df['similarity'] = similarities

    top = df.nlargest(n, 'similarity')

    return [
        {
            'date': str(row['date']),
            'regime': row['regime'],
            'similarity': round(float(row['similarity']), 4),
            'stress_score': float(row['overall_stress_score']) if row['overall_stress_score'] else None
        }
        for _, row in top.iterrows()
    ]


def get_forward_returns(similar_periods: list[dict], ticker: str, horizon_days: int = 60) -> dict:
    """For each similar historical period, look up what happened to the stock price afterward."""
    conn = get_connection()
    cursor = conn.cursor()

    forward_returns = []

    for period in similar_periods:
        period_date = period['date']

        cursor.execute("""
            SELECT date, close FROM stock_prices
            WHERE ticker = %s AND date >= %s
            ORDER BY date ASC LIMIT 1
        """, (ticker, period_date))
        start_row = cursor.fetchone()

        if not start_row:
            continue

        start_price = float(start_row[1])
        start_date = start_row[0]

        cursor.execute("""
            WITH ranked AS (
                SELECT date, close,
                       ROW_NUMBER() OVER (ORDER BY date ASC) as rn
                FROM stock_prices
                WHERE ticker = %s
            ),
            start_rn AS (
                SELECT rn FROM ranked WHERE date = %s
            )
            SELECT r.date, r.close
            FROM ranked r, start_rn s
            WHERE r.rn = s.rn + %s
        """, (ticker, start_date, horizon_days))
        end_row = cursor.fetchone()

        if not end_row:
            continue

        end_price = float(end_row[1])
        forward_return_pct = ((end_price - start_price) / start_price) * 100

        forward_returns.append({
            'period': str(period['date']),
            'similarity': period['similarity'],
            'start_price': start_price,
            'end_price': end_price,
            'forward_return_pct': round(forward_return_pct, 2)
        })

    cursor.close()
    conn.close()

    if not forward_returns:
        return {
            'ticker': ticker,
            'horizon_days': horizon_days,
            'sample_size': 0,
            'error': 'insufficient historical stock data for these periods'
        }

    returns = [r['forward_return_pct'] for r in forward_returns]

    return {
        'ticker': ticker,
        'horizon_days': horizon_days,
        'sample_size': len(returns),
        'median_return_pct': round(float(np.median(returns)), 2),
        'mean_return_pct': round(float(np.mean(returns)), 2),
        'best_case_pct': round(float(np.max(returns)), 2),
        'worst_case_pct': round(float(np.min(returns)), 2),
        'positive_outcomes': sum(1 for r in returns if r > 0),
        'negative_outcomes': sum(1 for r in returns if r <= 0),
        'confidence': 'high' if len(returns) >= 8 else 'medium' if len(returns) >= 4 else 'low',
        'confidence_note': f'Based on {len(returns)} similar historical periods',
        'historical_detail': forward_returns
    }


def store_fingerprints():
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

    print("\n=== Similar Historical Periods ===")
    similar = get_similar_periods(n=8)
    for p in similar:
        print(f"  {p['date']}  similarity={p['similarity']}  regime={p['regime']}")

    print("\n=== Forward Returns Analysis ===")
    for ticker in ['AAPL', 'TSLA', 'MSFT']:
        result = get_forward_returns(similar, ticker, horizon_days=60)
        print(f"\n{ticker} — {result['horizon_days']}d outlook:")
        print(f"  Median return:  {result.get('median_return_pct')}%")
        print(f"  Best case:      {result.get('best_case_pct')}%")
        print(f"  Worst case:     {result.get('worst_case_pct')}%")
        print(f"  Confidence:     {result.get('confidence')} ({result.get('confidence_note')})")
