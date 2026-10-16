import pandas as pd

from src.news import (
    calculate_move_days,
    normalize_url,
    tag_headline,
    titles_are_near_duplicates,
    url_hash,
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


def test_move_detection_uses_only_prior_90_returns_for_threshold():
    returns = [0.01 if index % 2 else -0.01 for index in range(100)] + [0.10]
    closes = [100.0]
    for value in returns:
        closes.append(closes[-1] * (1 + value))
    frame = pd.DataFrame({"date": pd.date_range("2025-01-01", periods=len(closes)), "close": closes})

    moves = calculate_move_days(frame)

    assert moves.iloc[-1]["date"] == frame.iloc[-1]["date"]
    assert round(moves.iloc[-1]["daily_return"], 4) == 0.1
