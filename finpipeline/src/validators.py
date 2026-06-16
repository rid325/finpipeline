# src/validators.py
from datetime import datetime
from fastapi import HTTPException


def validate_date(date_str: str, field_name: str) -> str:
    """Validates date string is in YYYY-MM-DD format. Returns the date string if valid."""
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
        return date_str
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} must be in YYYY-MM-DD format, got: {date_str}"
        )


def validate_date_range(start_date: str, end_date: str) -> None:
    """Validates start_date is before end_date."""
    start = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')
    if start >= end:
        raise HTTPException(
            status_code=400,
            detail=f"start_date ({start_date}) must be before end_date ({end_date})"
        )


def validate_ticker(ticker: str, valid_tickers: set) -> str:
    """Normalizes and validates a ticker symbol."""
    ticker = ticker.upper().strip()
    if not ticker.isalpha():
        raise HTTPException(
            status_code=400,
            detail=f"Ticker must contain only letters, got: {ticker}"
        )
    if ticker not in valid_tickers:
        raise HTTPException(
            status_code=404,
            detail=f"Ticker {ticker} not found. Valid tickers: {sorted(valid_tickers)}"
        )
    return ticker
