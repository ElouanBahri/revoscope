"""Live and historical market prices via yfinance (Revolut has no public API
for this, see project README)."""
from __future__ import annotations

import pandas as pd
import streamlit as st
import yfinance as yf

# Revolut exports the bare ticker with no exchange suffix, but Yahoo Finance
# requires one for anything not listed on a US exchange (US stocks like AAPL
# resolve as-is; a European UCITS ETF like VUAA does not). If a ticker fails
# to resolve, look it up on https://finance.yahoo.com/lookup and add the
# Yahoo-qualified symbol here — matching the exchange/currency the position
# was actually bought in keeps prices consistent with the recorded cost
# basis (e.g. a EUR purchase should map to the Xetra ".DE" listing, not a
# GBP one on the LSE, even though both technically track the same fund).
TICKER_OVERRIDES: dict[str, str] = {
    "VUAA": "VUAA.DE",  # Vanguard S&P 500 UCITS ETF (Acc), Xetra
    "EUNM": "EUNM.DE",  # iShares Core MSCI EM IMI UCITS ETF, Xetra
    "1TY": "1TY.DE",  # short-duration bond ETF, Xetra
}

# The 11 standard GICS sectors, so the sector-allocation view can show every
# sector even at $0.
ALL_SECTORS = [
    "Information Technology",
    "Financials",
    "Health Care",
    "Consumer Discretionary",
    "Communication Services",
    "Industrials",
    "Consumer Staples",
    "Energy",
    "Utilities",
    "Real Estate",
    "Materials",
]

# Yahoo Finance reports sectors using Morningstar's names, not GICS. Map them
# onto the GICS names above; entries absent here (Communication Services,
# Industrials, Energy, Utilities, Real Estate) already match.
_YAHOO_TO_GICS_SECTOR = {
    "Technology": "Information Technology",
    "Financial Services": "Financials",
    "Healthcare": "Health Care",
    "Consumer Cyclical": "Consumer Discretionary",
    "Consumer Defensive": "Consumer Staples",
    "Basic Materials": "Materials",
}


def _to_yahoo_symbol(ticker: str) -> str:
    return TICKER_OVERRIDES.get(ticker, ticker)


def _strip_tz(dates: pd.Series) -> pd.Series:
    """yfinance returns tz-aware timestamps (exchange local time); strip that
    so dates line up cleanly against our tz-naive transaction dates."""
    return dates.dt.tz_localize(None) if dates.dt.tz is not None else dates


@st.cache_data(ttl=300, show_spinner="Fetching live prices...")
def get_live_prices(tickers: tuple[str, ...]) -> dict[str, float]:
    """Latest close price per ticker. Missing/unresolvable tickers map to NaN
    rather than raising, so one bad symbol doesn't break the dashboard.
    """
    prices: dict[str, float] = {}
    for ticker in tickers:
        try:
            # A few days, not one: some exchanges report today's close with
            # a lag, and a bare period="1d" fetch can land on that one row
            # while it's still NaN, showing "no price" for an otherwise
            # perfectly resolvable ticker until the feed catches up.
            history = yf.Ticker(_to_yahoo_symbol(ticker)).history(period="5d")
            closes = history["Close"].dropna()
            prices[ticker] = float(closes.iloc[-1]) if not closes.empty else float("nan")
        except Exception:
            prices[ticker] = float("nan")
    return prices


@st.cache_data(ttl=3600, show_spinner="Fetching sector data...")
def get_sectors(tickers: tuple[str, ...]) -> dict[str, str]:
    """GICS sector per ticker. Falls back to 'Unknown' if the ticker's sector
    isn't reported by Yahoo Finance.

    Cached for an hour, not a day: a transient fetch failure (e.g. Yahoo
    rate-limiting) falls back to 'Unknown' same as a real gap, and caching
    that failure for 24h would leave it looking broken for a full day with
    no way to retry sooner than that.
    """
    sectors: dict[str, str] = {}
    for ticker in tickers:
        try:
            info = yf.Ticker(_to_yahoo_symbol(ticker)).info
            raw = info.get("sector") or "Unknown"
            sectors[ticker] = _YAHOO_TO_GICS_SECTOR.get(raw, raw)
        except Exception:
            sectors[ticker] = "Unknown"
    return sectors


@st.cache_data(ttl=3600, show_spinner="Fetching price history...")
def get_price_history(ticker: str, period: str = "6mo", start: str | None = None) -> pd.DataFrame:
    """Daily close-price history for one ticker, or an empty DataFrame if
    unavailable. Pass `start` (as 'YYYY-MM-DD') for a fixed start date
    instead of a relative `period` — used for since-investment and beta
    comparisons against a fixed benchmark window.
    """
    try:
        yf_ticker = yf.Ticker(_to_yahoo_symbol(ticker))
        history = yf_ticker.history(start=start) if start else yf_ticker.history(period=period)
        df = history.reset_index()[["Date", "Close"]].dropna(subset=["Close"])
        df["Date"] = _strip_tz(df["Date"])
        return df
    except Exception:
        return pd.DataFrame(columns=["Date", "Close"])
