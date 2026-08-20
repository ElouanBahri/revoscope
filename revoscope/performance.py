"""Performance analytics: CAPM beta regression and cash-flow-adjusted
portfolio performance versus a benchmark (S&P 500).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .portfolio import Position

BENCHMARK_TICKER = "^GSPC"
BENCHMARK_NAME = "S&P 500"


def _normalize_naive(dates: pd.Series) -> pd.Series:
    """Calendar date only, tz-naive — so trade dates line up with price-
    history dates (which are already tz-stripped in prices.py) when
    reindexing against the same DatetimeIndex."""
    dates = pd.to_datetime(dates)
    if dates.dt.tz is not None:
        dates = dates.dt.tz_localize(None)
    return dates.dt.normalize()


def compute_beta(stock_returns: pd.Series, market_returns: pd.Series) -> tuple[float, float, float]:
    """OLS regression of daily stock returns on daily market returns:
    stock = alpha + beta * market. This is the standard textbook way to
    estimate a stock's beta. Returns (beta, alpha, r_squared); all NaN if
    there isn't enough overlapping history.
    """
    aligned = pd.concat([stock_returns.rename("stock"), market_returns.rename("market")], axis=1, join="inner").dropna()
    if len(aligned) < 2 or aligned["market"].var() == 0:
        return float("nan"), float("nan"), float("nan")

    beta, alpha = np.polyfit(aligned["market"], aligned["stock"], 1)
    r_squared = float(np.corrcoef(aligned["market"], aligned["stock"])[0, 1] ** 2)
    return float(beta), float(alpha), r_squared


def price_return_index(prices: pd.Series) -> pd.Series:
    """Cumulative price-return index, rebased to 100 at the first value."""
    prices = prices.dropna()
    if prices.empty:
        return prices
    return prices / prices.iloc[0] * 100


def cash_flow_adjusted_index(values: pd.Series, cash_flows: pd.Series) -> pd.Series:
    """Time-weighted-return-style cumulative index (100 = start) from a daily
    market-value series and same-day external cash flows into/out of the
    position (positive = a buy, negative = a sell).

    Chain-linking daily returns this way — netting out each day's cash flow
    before measuring that day's price move — is the standard way pros
    benchmark a portfolio's performance without deposits/withdrawals
    distorting the comparison.
    """
    cash_flows = cash_flows.reindex(values.index).fillna(0.0)
    index = pd.Series(index=values.index, dtype=float)
    if values.empty:
        return index
    index.iloc[0] = 100.0
    for i in range(1, len(values)):
        prev_adjusted = values.iloc[i - 1] + cash_flows.iloc[i]
        # Guard against near-total exits: if a sale leaves only a few cents of
        # "base" behind, dividing by it turns ordinary rounding noise between
        # the sale proceeds and the prior close into a spurious ±100%+ swing
        # that would otherwise permanently distort the whole chained index.
        if prev_adjusted > max(1.0, 0.01 * values.iloc[i - 1]):
            daily_return = (values.iloc[i] - prev_adjusted) / prev_adjusted
        else:
            daily_return = 0.0
        index.iloc[i] = index.iloc[i - 1] * (1 + daily_return)
    return index


def build_portfolio_series(
    positions: dict[str, Position],
    price_histories: dict[str, pd.DataFrame],
    date_index: pd.DatetimeIndex,
) -> tuple[pd.Series, pd.Series]:
    """Reconstruct daily portfolio market value and same-day external cash
    flows (BUY = +amount, SELL = -amount) from each ticker's trade history
    and price history, aligned to `date_index`.
    """
    total_value = pd.Series(0.0, index=date_index)
    total_cash_flow = pd.Series(0.0, index=date_index)

    for ticker, pos in positions.items():
        if pos.trades.empty:
            continue
        trades = pos.trades[pos.trades["type"].isin(["BUY - MARKET", "SELL - MARKET"])].copy()
        if trades.empty:
            continue
        trades["date"] = _normalize_naive(trades["date"])
        sign = trades["type"].map({"BUY - MARKET": 1.0, "SELL - MARKET": -1.0})

        shares_delta = (trades["quantity"] * sign).groupby(trades["date"]).sum()
        shares_held = shares_delta.reindex(date_index, fill_value=0.0).cumsum()

        prices = price_histories.get(ticker)
        if prices is None or prices.empty:
            continue
        price_series = prices.set_index(prices["Date"].dt.normalize())["Close"].reindex(date_index, method="ffill")
        total_value = total_value.add(shares_held * price_series.fillna(0.0), fill_value=0.0)

        cash_flow = (trades["amount"] * sign).groupby(trades["date"]).sum()
        total_cash_flow = total_cash_flow.add(cash_flow.reindex(date_index, fill_value=0.0), fill_value=0.0)

    return total_value, total_cash_flow
