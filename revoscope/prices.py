"""Live and historical market prices via yfinance (Revolut has no public API
for this, see project README)."""
from __future__ import annotations

import pandas as pd
import streamlit as st
import yfinance as yf

# If a Revolut ticker doesn't resolve on Yahoo Finance, add the correct
# mapping here, e.g. {"REVOLUT_SYMBOL": "YAHOO_SYMBOL"}.
TICKER_OVERRIDES: dict[str, str] = {}


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


@st.cache_data(ttl=3600, show_spinner="Fetching price history...")
def get_price_history(ticker: str, period: str = "6mo") -> pd.DataFrame:
    """Daily close-price history for one ticker, or an empty DataFrame if
    unavailable."""
    try:
        history = yf.Ticker(_to_yahoo_symbol(ticker)).history(period=period)
        return history.reset_index()[["Date", "Close"]]
    except Exception:
        return pd.DataFrame(columns=["Date", "Close"])
