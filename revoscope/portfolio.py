"""Turn a transactions DataFrame into per-ticker positions: cost basis, realized
P&L, and dividends. Live prices (for unrealized P&L) are layered on separately
in prices.py, since that requires a network call.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .parser import DIVIDEND_TYPE

_OPEN_QTY_EPSILON = 1e-6


@dataclass
class Position:
    ticker: str
    quantity: float = 0.0
    cost_basis: float = 0.0
    realized_pnl: float = 0.0
    dividends: float = 0.0
    trades: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def avg_price(self) -> float:
        return self.cost_basis / self.quantity if self.quantity > _OPEN_QTY_EPSILON else 0.0

    @property
    def is_open(self) -> bool:
        return self.quantity > _OPEN_QTY_EPSILON


def build_positions(transactions: pd.DataFrame) -> dict[str, Position]:
    """Replay every trade/dividend in chronological order to build one
    Position per ticker, using average-cost-basis accounting.
    """
    positions: dict[str, Position] = {}
    trade_rows: dict[str, list] = {}

    for row in transactions.itertuples(index=False):
        if pd.isna(row.ticker):
            continue

        pos = positions.setdefault(row.ticker, Position(ticker=row.ticker))

        if row.type == "BUY - MARKET":
            pos.cost_basis += row.amount
            pos.quantity += row.quantity
            trade_rows.setdefault(row.ticker, []).append(row)
        elif row.type == "SELL - MARKET":
            avg_before = pos.avg_price
            cost_removed = row.quantity * avg_before
            pos.realized_pnl += row.amount - cost_removed
            pos.cost_basis -= cost_removed
            pos.quantity -= row.quantity
            trade_rows.setdefault(row.ticker, []).append(row)
        elif row.type == DIVIDEND_TYPE:
            pos.dividends += row.amount
            trade_rows.setdefault(row.ticker, []).append(row)

    for ticker, rows in trade_rows.items():
        positions[ticker].trades = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)

    return positions


def cash_balance(transactions: pd.DataFrame) -> float:
    """Net cash movement across the whole account (buys, sells, dividends,
    top-ups, withdrawals, and stock-promotion rewards/clawbacks).

    Every type except BUY already carries the correct sign in `amount`
    (sells/dividends/top-ups/rewards are positive inflows; withdrawals and
    clawbacks arrive pre-negated from Revolut).
    """
    cash = 0.0
    for row in transactions.itertuples(index=False):
        if row.type == "BUY - MARKET":
            cash -= row.amount
        else:
            cash += row.amount
    return cash
