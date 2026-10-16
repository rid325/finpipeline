from datetime import date

import pandas as pd
import pytest
from fastapi import HTTPException

from src.fetchers.macro_fetcher import load_curated_repo_rows
from src.fetchers.stock_fetcher import normalize_yahoo_history
from src.validators import validate_ticker


def test_ist_session_date_is_not_shifted_to_previous_utc_day():
    index = pd.DatetimeIndex(["2026-10-16 00:00:00"], tz="Asia/Kolkata", name="Date")
    frame = pd.DataFrame(
        {"Open": [100], "High": [102], "Low": [99], "Close": [101],
         "Adj Close": [100.5], "Volume": [10]},
        index=index,
    )

    normalized = normalize_yahoo_history(frame, "^NSEI", "Asia/Kolkata")

    assert normalized.loc[0, "date"] == date(2026, 10, 16)
    assert normalized.loc[0, "adj close"] == 100.5


def test_missing_adjusted_close_falls_back_to_raw_close():
    frame = pd.DataFrame(
        {"date": ["2026-10-16"], "open": [100], "high": [102], "low": [99],
         "close": [101], "volume": [None]}
    )
    normalized = normalize_yahoo_history(frame, "USDINR=X", "Asia/Kolkata")
    assert normalized.loc[0, "adj close"] == 101


@pytest.mark.parametrize("ticker", ["^NSEI", "RELIANCE.NS", "USDINR=X", "BZ=F"])
def test_yahoo_symbols_are_accepted_by_validation(ticker):
    assert validate_ticker(ticker, {ticker}) == ticker


def test_unsupported_ticker_characters_are_rejected():
    with pytest.raises(HTTPException) as error:
        validate_ticker("NSEI;DROP", {"NSEI;DROP"})
    assert error.value.status_code == 400


def test_curated_repo_rate_rows_have_real_source_backed_values():
    rows = load_curated_repo_rows()
    assert rows == [
        ("2024-07-05", 6.5),
        ("2025-03-28", 6.25),
        ("2025-04-11", 6.0),
        ("2025-06-06", 5.5),
    ]
