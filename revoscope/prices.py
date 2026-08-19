"""Live and historical market prices via yfinance (Revolut has no public API
for this, see project README)."""
from __future__ import annotations

import pandas as pd
import streamlit as st
import yfinance as yf

# If a Revolut ticker doesn't resolve on Yahoo Finance, add the correct
# mapping here, e.g. {"REVOLUT_SYMBOL": "YAHOO_SYMBOL"}.
TICKER_OVERRIDES: dict[str, str] = {}

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


@st.cache_data(ttl=300, show_spinner="Fetching live prices...")
def get_live_prices(tickers: tuple[str, ...]) -> dict[str, float]:
    """Latest close price per ticker. Missing/unresolvable tickers map to NaN
    rather than raising, so one bad symbol doesn't break the dashboard.
    """
    prices: dict[str, float] = {}
    for ticker in tickers:
        try:
            history = yf.Ticker(_to_yahoo_symbol(ticker)).history(period="1d")
            prices[ticker] = float(history["Close"].iloc[-1]) if not history.empty else float("nan")
        except Exception:
            prices[ticker] = float("nan")
    return prices


@st.cache_data(ttl=86400, show_spinner="Fetching sector data...")
def get_sectors(tickers: tuple[str, ...]) -> dict[str, str]:
    """GICS sector per ticker. Falls back to 'Unknown' if the ticker's sector
    isn't reported by Yahoo Finance.
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
def get_price_history(ticker: str, period: str = "6mo") -> pd.DataFrame:
    """Daily close-price history for one ticker, or an empty DataFrame if
    unavailable."""
    try:
        history = yf.Ticker(_to_yahoo_symbol(ticker)).history(period=period)
        return history.reset_index()[["Date", "Close"]]
    except Exception:
        return pd.DataFrame(columns=["Date", "Close"])
