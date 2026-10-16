from datetime import date

from src.methodology import age_freshness, market_freshness


def test_friday_market_data_is_fresh_over_weekend():
    assert market_freshness(date(2026, 10, 16), date(2026, 10, 18)) == "fresh"


def test_market_freshness_distinguishes_delay_and_stale():
    assert market_freshness(date(2026, 10, 16), date(2026, 10, 20)) == "delayed"
    assert market_freshness(date(2026, 10, 16), date(2026, 10, 22)) == "stale"
    assert market_freshness(None, date(2026, 10, 22)) == "never_loaded"


def test_macro_thresholds_follow_series_frequency():
    today = date(2026, 10, 17)
    assert age_freshness(date(2026, 9, 1), today, "monthly") == "delayed"
    assert age_freshness(date(2026, 6, 30), today, "quarterly") == "fresh"
