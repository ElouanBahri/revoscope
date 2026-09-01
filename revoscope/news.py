"""Macro/economy news and per-holding news — for the News tab.

Two free, no-API-key sources, in keeping with the rest of revoscope:

- Headlines (both the macro overview and the per-ticker portfolio news) come
  from Yahoo Finance via yfinance: `yf.Search(...).news` for topic search
  (used for the Fed/Europe/Asia overview) and `yf.Ticker(...).news` for a
  specific security (used for the portfolio section) — the same feeds shown
  on finance.yahoo.com, each item carrying its own publisher and link so the
  source is always attributable.
- Actual policy-rate figures (not just headlines about them) come from
  FRED's public `fredgraph.csv` export. This is the same St. Louis Fed data
  behind the normal FRED API, just served without requiring an API key.

Central bank meeting *dates* aren't available from either of those — they're
a published calendar, not a data series — so the small lookup tables below
are maintained by hand from the official sources linked next to them.
"""
from __future__ import annotations

import io

import pandas as pd
import requests
import streamlit as st
import yfinance as yf

from .prices import to_yahoo_symbol

FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"

# Published up to ~18 months ahead by each central bank and essentially
# never move once announced — update when the next year's calendar comes
# out. Sources:
#   Fed: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
#   ECB: https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html
FOMC_MEETINGS = [
    ("2026-01-27", "2026-01-28"),
    ("2026-03-17", "2026-03-18"),
    ("2026-04-28", "2026-04-29"),
    ("2026-06-16", "2026-06-17"),
    ("2026-07-28", "2026-07-29"),
    ("2026-09-15", "2026-09-16"),
    ("2026-10-27", "2026-10-28"),
    ("2026-12-08", "2026-12-09"),
    ("2027-01-26", "2027-01-27"),
    ("2027-03-16", "2027-03-17"),
    ("2027-04-27", "2027-04-28"),
    ("2027-06-08", "2027-06-09"),
    ("2027-07-27", "2027-07-28"),
    ("2027-09-14", "2027-09-15"),
    ("2027-10-26", "2027-10-27"),
    ("2027-12-07", "2027-12-08"),
]
FOMC_SOURCE_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"

ECB_MEETINGS = [
    ("2026-09-09", "2026-09-10"),
    ("2026-10-28", "2026-10-29"),
    ("2026-12-16", "2026-12-17"),
]
ECB_SOURCE_URL = "https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html"


def next_meeting(meetings: list[tuple[str, str]], today: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    """First meeting (start, end) that hasn't ended yet, or None if `today`
    is past every date on file — happens once the hand-maintained table
    above runs out, not from a fetch failure."""
    today = today.normalize()
    for start, end in meetings:
        end_ts = pd.Timestamp(end)
        if end_ts >= today:
            return pd.Timestamp(start), end_ts
    return None


@st.cache_data(ttl=3600, show_spinner=False)
def _fred_series_latest(series: str) -> tuple[float, pd.Timestamp] | None:
    """Most recent (value, date) of a FRED series via its public CSV export
    — `fredgraph.csv` is served openly, unlike FRED's JSON API which needs a
    registered key. Returns None on any fetch/parse failure."""
    try:
        resp = requests.get(FRED_CSV_URL.format(series=series), timeout=10)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
        df.columns = ["date", "value"]
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna()
        if df.empty:
            return None
        last = df.sort_values("date").iloc[-1]
        return float(last["value"]), pd.Timestamp(last["date"])
    except Exception:
        return None


def get_fed_funds_target_range() -> dict | None:
    """Current Fed funds target range (upper/lower bound), the figure the
    FOMC actually sets — sourced from FRED series DFEDTARU/DFEDTARL."""
    upper = _fred_series_latest("DFEDTARU")
    lower = _fred_series_latest("DFEDTARL")
    if upper is None or lower is None:
        return None
    upper_value, as_of = upper
    lower_value, _ = lower
    return {
        "display": f"{lower_value:.2f}% – {upper_value:.2f}%",
        "as_of": as_of,
        "source_name": "FRED · Federal Reserve Bank of St. Louis",
        "source_url": "https://fred.stlouisfed.org/series/DFEDTARU",
    }


def get_ecb_deposit_rate() -> dict | None:
    """Current ECB deposit facility rate — the ECB's main policy-steering
    rate since 2022 — sourced from FRED series ECBDFR."""
    result = _fred_series_latest("ECBDFR")
    if result is None:
        return None
    value, as_of = result
    return {
        "display": f"{value:.2f}%",
        "as_of": as_of,
        "source_name": "FRED · Federal Reserve Bank of St. Louis",
        "source_url": "https://fred.stlouisfed.org/series/ECBDFR",
    }


def _normalize_search_item(raw: dict) -> dict | None:
    url = raw.get("link")
    if not url:
        return None
    publish_time = raw.get("providerPublishTime")
    published = pd.Timestamp(publish_time, unit="s", tz="UTC") if publish_time else None
    return {
        "title": raw.get("title") or "Untitled",
        "source": raw.get("publisher") or "Unknown source",
        "url": url,
        "published": published,
    }


def _normalize_ticker_item(raw: dict) -> dict | None:
    # Recent yfinance nests everything under "content"; tolerate the older
    # flat shape too in case yfinance reverts or a cached response differs.
    content = raw.get("content", raw)
    link = content.get("clickThroughUrl") or content.get("canonicalUrl") or {}
    url = link.get("url") if isinstance(link, dict) else raw.get("link")
    if not url:
        return None
    provider = content.get("provider") or {}
    source = provider.get("displayName") if isinstance(provider, dict) else None
    pub_raw = content.get("pubDate") or raw.get("providerPublishTime")
    try:
        published = pd.Timestamp(pub_raw, unit="s" if isinstance(pub_raw, (int, float)) else None, tz="UTC") if pub_raw else None
    except Exception:
        published = None
    return {
        "title": content.get("title") or raw.get("title") or "Untitled",
        "source": source or raw.get("publisher") or "Unknown source",
        "url": url,
        "published": published,
    }


def _sort_recent_first(items: list[dict]) -> list[dict]:
    epoch = pd.Timestamp.min.tz_localize("UTC")
    return sorted(items, key=lambda i: i["published"] or epoch, reverse=True)


@st.cache_data(ttl=900, show_spinner=False)
def search_news(query: str, count: int = 8) -> list[dict]:
    """Recent headlines matching a free-text query, via Yahoo Finance search
    (yfinance's `Search`, no API key). Used for the macro overview, where
    there's no single ticker to key off of.

    Yahoo's search endpoint matches best on a short, plain phrase (2-3
    words) — a long, keyword-stuffed query reliably comes back empty rather
    than merely narrower, which is why the macro overview combines several
    short queries via `search_news_topics` instead of one long one.

    Each item: title, source, url, published (UTC timestamp or None).
    """
    try:
        raw_results = yf.Search(query, news_count=count).news
    except Exception:
        return []
    items = [item for r in raw_results if (item := _normalize_search_item(r)) is not None]
    return _sort_recent_first(items)


def search_news_topics(queries: list[str], count_per_query: int = 5, limit: int = 5) -> list[dict]:
    """Merge several short-query `search_news` calls into one deduplicated,
    most-recent-first list — covers a region/topic more broadly than any
    single short query would, without falling back to the long queries that
    Yahoo's search silently drops (see `search_news`)."""
    seen_urls: set[str] = set()
    merged: list[dict] = []
    for query in queries:
        for item in search_news(query, count=count_per_query):
            if item["url"] not in seen_urls:
                seen_urls.add(item["url"])
                merged.append(item)
    return _sort_recent_first(merged)[:limit]


@st.cache_data(ttl=900, show_spinner=False)
def get_ticker_news(ticker: str, count: int = 5) -> list[dict]:
    """Recent news for one ticker straight from Yahoo Finance (yfinance's
    `Ticker.news`) — automatically specific to whatever's actually in the
    uploaded portfolio, no per-portfolio configuration needed. Returns an
    empty list for tickers Yahoo has no news for (e.g. bond CUSIPs/ISINs, or
    a genuine fetch failure) rather than raising."""
    try:
        raw_results = yf.Ticker(to_yahoo_symbol(ticker)).news
    except Exception:
        return []
    items = [item for r in raw_results if (item := _normalize_ticker_item(r)) is not None]
    return _sort_recent_first(items)[:count]


def time_ago(published: pd.Timestamp | None, now: pd.Timestamp) -> str:
    """Short relative-age string ('3h ago', '2d ago') for a headline's
    published time, so recency is visible without parsing a full timestamp."""
    if published is None:
        return "date unknown"
    hours = (now - published).total_seconds() / 3600
    if hours < 0:
        return "just now"
    if hours < 1:
        return "just now"
    if hours < 24:
        return f"{int(hours)}h ago"
    return f"{int(hours // 24)}d ago"
