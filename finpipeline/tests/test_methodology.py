from datetime import date, datetime, timezone
from pathlib import Path

from src.methodology import (
    age_freshness,
    build_job_freshness,
    job_freshness,
    market_freshness,
)


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


def test_market_job_freshness_ignores_weekend_days():
    result = job_freshness(
        "market-india",
        datetime(2026, 10, 16, 11, tzinfo=timezone.utc),
        None,
        datetime(2026, 10, 18, 20, tzinfo=timezone.utc),
    )
    assert result == {
        "expected_cadence": "weekdays after exchange close",
        "threshold_unit": "business_days",
        "fresh_threshold": 1,
        "delayed_threshold": 2,
        "age": 0,
        "status": "fresh",
    }


def test_daily_job_thresholds_and_newer_problem_are_explicit():
    now = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
    delayed = job_freshness(
        "macro-all", datetime(2026, 10, 15, 12, tzinfo=timezone.utc), None, now
    )
    assert delayed["status"] == "delayed"
    assert delayed["age"] == 48.0
    assert delayed["fresh_threshold"] == 36
    assert delayed["delayed_threshold"] == 72

    problem = job_freshness(
        "regime-india-us-v1",
        datetime(2026, 10, 17, 8, tzinfo=timezone.utc),
        datetime(2026, 10, 17, 9, tzinfo=timezone.utc),
        now,
    )
    assert problem["status"] == "problem"


def test_backfill_is_completed_not_eventually_stale():
    result = job_freshness(
        "market-india-backfill",
        datetime(2025, 1, 1, tzinfo=timezone.utc),
        None,
        datetime(2026, 10, 17, tzinfo=timezone.utc),
    )
    assert result["status"] == "completed"
    assert result["expected_cadence"] == "one-time backfill"
    assert result["fresh_threshold"] is None


def test_expected_jobs_are_visible_before_first_run():
    jobs = build_job_freshness([], datetime(2026, 10, 17, tzinfo=timezone.utc))
    assert {job["job_name"] for job in jobs} == {
        "macro-all", "market-global", "market-india", "news-india", "regime-india-us-v1",
    }
    assert {job["status"] for job in jobs} == {"never_succeeded"}


def test_dashboard_renders_per_job_freshness_contract():
    dashboard = (Path(__file__).parents[1] / "dashboard" / "index.html").read_text()
    assert 'id="job-freshness"' in dashboard
    assert "x.expected_cadence" in dashboard
    assert "x.fresh_threshold" in dashboard
    assert "x.delayed_threshold" in dashboard


def test_regime_panel_has_skeleton_wake_and_empty_states():
    dashboard = (Path(__file__).parents[1] / "dashboard" / "index.html").read_text()
    assert 'id="regime-title" data-state="loading"' in dashboard
    assert 'id="regime-grid" aria-live="polite"' in dashboard
    assert "Server is waking; checking persisted regime history" in dashboard
    assert "No regime result was returned" in dashboard
    assert ">Loading India regime" not in dashboard
