# src/backtest.py
import numpy as np
from src.db import get_connection


def run_regime_backtest(ticker: str, horizon_days: int = 60) -> dict:
    """
    For each regime type in history, calculate average forward returns.
    Validates whether regime classification has predictive value.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT date, regime, overall_stress_score
        FROM macro_fingerprints
        ORDER BY date ASC
    """)
    fingerprint_rows = cursor.fetchall()
    cursor.close()
    conn.close()

    results_by_regime = {'expansionary': [], 'transitional': [], 'contractionary': []}

    conn = get_connection()
    cursor = conn.cursor()

    for date_val, regime, stress_score in fingerprint_rows:
        date_str = str(date_val)

        # only use periods where stock data actually exists at that date
        cursor.execute("""
            SELECT date, close FROM stock_prices
            WHERE ticker = %s AND date = %s
        """, (ticker, date_str))
        exact_row = cursor.fetchone()
        if not exact_row:
            continue  # skip fingerprint periods with no stock data

        start_price = float(exact_row[1])
        start_date = exact_row[0]

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
            SELECT r.close
            FROM ranked r, start_rn s
            WHERE r.rn = s.rn + %s
        """, (ticker, start_date, horizon_days))
        end_row = cursor.fetchone()
        if not end_row:
            continue

        fwd_return = ((float(end_row[0]) - start_price) / start_price) * 100
        results_by_regime[regime].append(fwd_return)

    cursor.close()
    conn.close()

    summary = {}
    for regime, returns in results_by_regime.items():
        if not returns:
            continue
        summary[regime] = {
            'sample_size': len(returns),
            'median_return_pct': round(float(np.median(returns)), 2),
            'mean_return_pct': round(float(np.mean(returns)), 2),
            'positive_rate': round(sum(1 for r in returns if r > 0) / len(returns) * 100, 1),
            'best_case_pct': round(float(np.max(returns)), 2),
            'worst_case_pct': round(float(np.min(returns)), 2)
        }

    return {
        'ticker': ticker,
        'horizon_days': horizon_days,
        'backtest_results': summary,
        'interpretation': _interpret_backtest(summary)
    }


def _interpret_backtest(summary: dict) -> str:
    if 'expansionary' not in summary or 'contractionary' not in summary:
        return 'Insufficient data for interpretation'

    exp_median = summary['expansionary']['median_return_pct']
    con_median = summary['contractionary']['median_return_pct']

    if exp_median > con_median + 3:
        return (f'Regime classification shows meaningful signal: expansionary periods produced '
                f'{exp_median:.1f}% median returns vs {con_median:.1f}% in contractionary periods')
    elif abs(exp_median - con_median) <= 3:
        return (f'Regime classification shows weak signal for this ticker: returns are similar '
                f'across regimes ({exp_median:.1f}% vs {con_median:.1f}%)')
    else:
        return (f'Unexpected pattern: contractionary periods produced higher returns '
                f'({con_median:.1f}% vs {exp_median:.1f}%) — may indicate mean-reversion behavior')


if __name__ == "__main__":
    for ticker in ['AAPL', 'TSLA', 'MSFT', 'GOOGL']:
        print(f"\n=== Backtest: {ticker} (60-day horizon) ===")
        result = run_regime_backtest(ticker, horizon_days=60)
        for regime, stats in result['backtest_results'].items():
            print(f"  {regime:<15} median={stats['median_return_pct']:>6.1f}%  "
                  f"pos_rate={stats['positive_rate']}%  n={stats['sample_size']}")
        print(f"  → {result['interpretation']}")
