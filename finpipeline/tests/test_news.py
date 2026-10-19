import csv
from datetime import datetime, timezone
from pathlib import Path
import time

import pandas as pd

from src.news import (
    calculate_move_days,
    evaluate_tagging_rows,
    move_days_in_window,
    normalize_url,
    tag_headline,
    titles_are_near_duplicates,
    url_hash,
    _recent_dated_entries,
)


def test_url_normalization_removes_tracking_and_fragment():
    left = "https://Example.com/story/?utm_source=rss&id=4#top"
    right = "https://example.com/story?id=4"
    assert normalize_url(left) == right
    assert url_hash(left) == url_hash(right)


def test_near_duplicate_titles_ignore_word_order_and_punctuation():
    assert titles_are_near_duplicates(
        "Nifty rises as bank shares gain strongly",
        "Bank shares gain strongly as Nifty rises!",
    )
    assert not titles_are_near_duplicates("Nifty rises today", "Brent crude falls")


def test_plain_alias_tagger_respects_boundaries_and_ticker_case():
    assert tag_headline("TCS and Infosys lift Nifty 50 as IT sector gains") == {
        "tickers": ["INFY.NS", "TCS.NS", "^NSEI"],
        "sectors": ["technology"],
    }
    assert tag_headline("Airtel infrastructure spending increases")["tickers"] == ["BHARTIARTL.NS"]
    assert "TCS.NS" not in tag_headline("tcs is lowercase in this synthetic fixture")["tickers"]
    assert tag_headline("Jio and Airtel compete for subscribers")["tickers"] == [
        "BHARTIARTL.NS", "RELIANCE.NS",
    ]


def test_news_evaluation_contains_50_real_labeled_headlines():
    path = Path(__file__).resolve().parents[2] / "eval" / "news_tagging.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8")))

    assert len(rows) == 50
    assert {row["source"] for row in rows} == {
        "Economic Times Markets", "Mint Markets", "Business Standard Markets",
    }
    assert all(row["title"] and row["published_at"] for row in rows)
    result = evaluate_tagging_rows(rows)
    assert (result["true_positive"], result["false_positive"], result["false_negative"]) == (23, 0, 12)
    assert (result["precision"], result["recall"]) == (1.0, 0.6571)


def test_recent_feed_items_require_plausible_timestamps():
    now = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)
    entries = [
        {"title": "current", "published_parsed": time.gmtime(now.timestamp())},
        {"title": "undated"},
        {"title": "stale", "published_parsed": time.gmtime(datetime(2024, 4, 23, tzinfo=timezone.utc).timestamp())},
        {"title": "future", "published_parsed": time.gmtime(datetime(2026, 10, 22, tzinfo=timezone.utc).timestamp())},
    ]

    assert [entry["title"] for entry, _ in _recent_dated_entries(entries, now)] == ["current"]


def test_move_detection_uses_only_prior_90_returns_for_threshold():
    returns = [0.01 if index % 2 else -0.01 for index in range(100)] + [0.10]
    closes = [100.0]
    for value in returns:
        closes.append(closes[-1] * (1 + value))
    frame = pd.DataFrame({"date": pd.date_range("2025-01-01", periods=len(closes)), "close": closes})

    moves = calculate_move_days(frame)

    assert moves.iloc[-1]["date"] == frame.iloc[-1]["date"]
    assert round(moves.iloc[-1]["daily_return"], 4) == 0.1


def test_move_window_excludes_old_events_but_keeps_lookback_context():
    returns = [0.01 if index % 2 else -0.01 for index in range(95)]
    returns += [0.12]
    returns += [0.01 if index % 2 else -0.01 for index in range(30)]
    closes = [100.0]
    for value in returns:
        closes.append(closes[-1] * (1 + value))
    frame = pd.DataFrame({"date": pd.date_range("2025-01-01", periods=len(closes)), "close": closes})

    all_moves = calculate_move_days(frame)
    recent_moves = move_days_in_window(frame, days=30)

    assert not all_moves.empty
    assert recent_moves.empty
