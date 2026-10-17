"""Licensed-opt-in RSS ingestion, deterministic tagging, and move-day joins."""
from __future__ import annotations

import calendar
from datetime import datetime, timedelta, timezone
import hashlib
import html
import re
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import pandas as pd
import requests

from src.config import NEWS_FEEDS_ENABLED
from src.db import get_connection


FEEDS = {
    "economic-times-markets": {
        "source": "Economic Times Markets",
        "url": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        "status": "license_required",
    },
    "mint-markets": {
        "source": "Mint Markets",
        "url": "https://www.livemint.com/rss/markets",
        "status": "license_required",
    },
    "business-standard-markets": {
        "source": "Business Standard Markets",
        "url": "https://www.business-standard.com/rss/markets-106.rss",
        "status": "license_required",
    },
    "moneycontrol-markets": {
        "source": "Moneycontrol Markets",
        "url": None,
        "status": "unavailable_http_403",
    },
}

ALIASES = {
    "^NSEI": ["Nifty 50", "Nifty"],
    "^BSESN": ["Sensex", "BSE Sensex"],
    "^NSEBANK": ["Bank Nifty", "Nifty Bank"],
    "^INDIAVIX": ["India VIX"],
    "RELIANCE.NS": ["Reliance Industries", "Reliance"],
    "TCS.NS": ["Tata Consultancy Services", "TCS"],
    "HDFCBANK.NS": ["HDFC Bank"],
    "INFY.NS": ["Infosys"],
    "ICICIBANK.NS": ["ICICI Bank"],
    "HINDUNILVR.NS": ["Hindustan Unilever", "HUL"],
    "ITC.NS": ["ITC"],
    "SBIN.NS": ["State Bank of India", "SBI"],
    "BHARTIARTL.NS": ["Bharti Airtel", "Airtel"],
    "LT.NS": ["Larsen & Toubro", "L&T"],
}

SECTOR_ALIASES = {
    "financials": ["bank", "banks", "banking", "financials"],
    "technology": ["IT sector", "technology", "software"],
    "energy": ["oil", "crude", "energy"],
    "consumer": ["FMCG", "consumer goods"],
    "telecom": ["telecom"],
    "industrial": ["infrastructure", "capital goods"],
}

TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gclid", "fbclid"}


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = urlencode(sorted((key, value) for key, value in parse_qsl(parts.query) if key.lower() not in TRACKING_PARAMS))
    path = re.sub(r"/{2,}", "/", parts.path).rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower() or "https", parts.netloc.lower(), path, query, ""))


def url_hash(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()


def _contains_alias(text: str, alias: str) -> bool:
    flags = 0 if alias.isupper() and len(alias) <= 5 else re.IGNORECASE
    return bool(re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text, flags))


def tag_headline(title: str) -> dict[str, list[str]]:
    tickers = sorted(ticker for ticker, aliases in ALIASES.items() if any(_contains_alias(title, alias) for alias in aliases))
    sectors = sorted(sector for sector, aliases in SECTOR_ALIASES.items() if any(_contains_alias(title, alias) for alias in aliases))
    return {"tickers": tickers, "sectors": sectors}


def _title_tokens(title: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", title.lower()))


def titles_are_near_duplicates(left: str, right: str, threshold: float = 0.88) -> bool:
    left_tokens, right_tokens = _title_tokens(left), _title_tokens(right)
    if not left_tokens or not right_tokens:
        return False
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens) >= threshold


def _published_at(entry) -> datetime:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
    return datetime.now(timezone.utc)


def _plain_snippet(entry) -> str | None:
    raw = entry.get("summary") or entry.get("description")
    if not raw:
        return None
    text = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    return re.sub(r"\s+", " ", text).strip()[:500] or None


def fetch_and_store_news() -> dict:
    conn = get_connection()
    cursor = conn.cursor()
    started_at = datetime.now(timezone.utc)
    started_clock = time.monotonic()
    cursor.execute("""
        INSERT INTO pipeline_runs (source, job_name, status, started_at)
        VALUES ('rss', 'news-india', 'running', %s) RETURNING id
    """, (started_at,))
    run_id = cursor.fetchone()[0]
    conn.commit()
    rows_written, warnings, skipped = 0, [], []

    for feed_id, config in FEEDS.items():
        if feed_id not in NEWS_FEEDS_ENABLED or not config["url"]:
            skipped.append({"feed": feed_id, "reason": config["status"]})
            continue
        try:
            response = requests.get(config["url"], timeout=20, headers={"User-Agent": "FinPipeline/1.0 (+portfolio research)"})
            response.raise_for_status()
            parsed = feedparser.parse(response.content)
            for entry in parsed.entries:
                title, link = str(entry.get("title", "")).strip(), str(entry.get("link", "")).strip()
                if not title or not link:
                    continue
                published = _published_at(entry)
                cursor.execute(
                    "SELECT title FROM news_articles WHERE published_at >= %s",
                    (published - timedelta(hours=48),),
                )
                if any(titles_are_near_duplicates(title, row[0]) for row in cursor.fetchall()):
                    continue
                normalized = normalize_url(link)
                cursor.execute("""
                    INSERT INTO news_articles (source, title, url, url_hash, published_at, snippet)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (url_hash) DO NOTHING RETURNING id
                """, (config["source"], title, normalized, url_hash(normalized), published, _plain_snippet(entry)))
                inserted = cursor.fetchone()
                if not inserted:
                    continue
                article_id = inserted[0]
                tags = tag_headline(title)
                for tag_type, values in (("ticker", tags["tickers"]), ("sector", tags["sectors"])):
                    for tag in values:
                        cursor.execute(
                            "INSERT INTO news_tags (article_id, tag_type, tag) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                            (article_id, tag_type, tag),
                        )
                rows_written += 1
            conn.commit()
        except Exception as error:
            conn.rollback()
            warnings.append(f"{feed_id}: {error}")

    cursor.execute("DELETE FROM news_articles WHERE published_at < NOW() - INTERVAL '365 days'")
    conn.commit()
    cursor.execute("""
        UPDATE pipeline_runs SET status=%s, records_fetched=%s, error_message=%s,
            completed_at=%s, duration_ms=%s WHERE id=%s
    """, ('partial' if warnings else 'success', rows_written, '\n'.join(warnings) or None,
          datetime.now(timezone.utc), round((time.monotonic() - started_clock) * 1000), run_id))
    conn.commit()
    cursor.close()
    conn.close()
    return {"run_id": run_id, "total_inserted": rows_written, "errors": [], "warnings": warnings, "skipped": skipped}


def calculate_move_days(prices: pd.DataFrame, sigma: float = 2.0, lookback: int = 90) -> pd.DataFrame:
    frame = prices.sort_values("date").copy()
    frame["daily_return"] = frame["close"].pct_change()
    frame["trailing_std"] = frame["daily_return"].rolling(lookback, min_periods=lookback).std().shift(1)
    frame["is_move"] = frame["daily_return"].abs() > sigma * frame["trailing_std"]
    return frame[frame["is_move"]].copy()


def move_days_in_window(
    prices: pd.DataFrame, days: int, sigma: float = 2.0, lookback: int = 90,
) -> pd.DataFrame:
    """Detect moves with lookback context, then keep only the requested sessions."""
    ordered = prices.sort_values("date")
    requested_dates = set(ordered.tail(days)["date"])
    moves = calculate_move_days(ordered, sigma=sigma, lookback=lookback)
    return moves[moves["date"].isin(requested_dates)].copy()


def query_news(
    ticker: str | None = None, sector: str | None = None,
    from_date: str | None = None, to_date: str | None = None,
    source: str | None = None, limit: int = 50,
) -> list[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    clauses, params = [], []
    for tag_type, tag in (("ticker", ticker), ("sector", sector)):
        if tag:
            clauses.append("EXISTS (SELECT 1 FROM news_tags f WHERE f.article_id=a.id AND f.tag_type=%s AND f.tag=%s)")
            params.extend([tag_type, tag])
    if from_date:
        clauses.append("a.published_at >= %s")
        params.append(from_date)
    if to_date:
        clauses.append("a.published_at < (%s::date + INTERVAL '1 day')")
        params.append(to_date)
    if source:
        clauses.append("a.source = %s")
        params.append(source)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    params.append(limit)
    cursor.execute(f"""
        SELECT a.id, a.source, a.title, a.url, a.published_at, a.fetched_at, a.snippet,
            ARRAY(SELECT t.tag FROM news_tags t WHERE t.article_id=a.id AND t.tag_type='ticker' ORDER BY t.tag),
            ARRAY(SELECT t.tag FROM news_tags t WHERE t.article_id=a.id AND t.tag_type='sector' ORDER BY t.tag)
        FROM news_articles a {where} ORDER BY a.published_at DESC LIMIT %s
    """, params)
    keys = ("id", "source", "title", "url", "published_at", "fetched_at", "snippet", "tickers", "sectors")
    results = [dict(zip(keys, row)) for row in cursor.fetchall()]
    cursor.close()
    conn.close()
    for item in results:
        item["published_at"] = item["published_at"].isoformat()
        item["fetched_at"] = item["fetched_at"].isoformat()
    return results


def get_move_days(ticker: str, days: int = 365) -> list[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT timezone FROM instruments WHERE ticker=%s AND active=TRUE", (ticker,))
    instrument = cursor.fetchone()
    if not instrument:
        cursor.close(); conn.close()
        raise ValueError("unknown ticker")
    market_timezone = instrument[0]
    cursor.execute("""
        SELECT date, COALESCE(adjusted_close, close)
        FROM stock_prices WHERE ticker=%s
        ORDER BY date DESC LIMIT %s
    """, (ticker, days + 91))
    rows = cursor.fetchall()
    prices = pd.DataFrame(rows, columns=["date", "close"])
    if prices.empty:
        cursor.close(); conn.close()
        return []
    prices["close"] = prices["close"].astype(float)
    moves = move_days_in_window(prices, days)
    output = []
    for _, move in moves.iterrows():
        cursor.execute("""
            SELECT a.source, a.title, a.url, a.published_at
            FROM news_articles a JOIN news_tags t ON t.article_id=a.id
            WHERE t.tag_type='ticker' AND t.tag=%s
              AND (a.published_at AT TIME ZONE %s)::date=%s
            ORDER BY a.published_at
        """, (ticker, market_timezone, move["date"]))
        headlines = [
            {"source": row[0], "title": row[1], "url": row[2], "published_at": row[3].isoformat()}
            for row in cursor.fetchall()
        ]
        output.append({
            "date": str(move["date"]),
            "daily_return_pct": round(float(move["daily_return"]) * 100, 3),
            "threshold_pct": round(float(move["trailing_std"]) * 200, 3),
            "headlines_on_the_day": headlines,
        })
    cursor.close()
    conn.close()
    return output
