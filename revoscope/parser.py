"""Parse Revolut stock-trading CSV exports into a clean transactions DataFrame."""
from __future__ import annotations

import re

import pandas as pd

STOCK_TRADE_TYPES = {"BUY - MARKET", "SELL - MARKET"}
DIVIDEND_TYPE = "DIVIDEND"
CASH_TYPES = {
    "CASH TOP-UP",
    "CASH WITHDRAWAL",
    "STOCKS PROMOTION REWARD",
    "STOCKS PROMOTION CLAWBACK",
}

_COLUMN_MAP = {
    "Date": "date",
    "Ticker": "ticker",
    "Type": "type",
    "Quantity": "quantity",
    "Price per share": "price",
    "Total Amount": "amount",
    "Currency": "currency",
    "FX Rate": "fx_rate",
}

_MONEY_RE = re.compile(r"^[A-Z]{3}\s*(-?[\d,]+\.?\d*)$")


def _parse_money(value: object) -> float:
    """Turn a 'USD 93.78' style cell into a plain float."""
    if pd.isna(value) or value == "":
        return float("nan")
    match = _MONEY_RE.match(str(value).strip())
    if not match:
        raise ValueError(f"Unrecognized money format: {value!r}")
    return float(match.group(1).replace(",", ""))


def load_transactions(csv_path: str) -> pd.DataFrame:
    """Load a Revolut transactions CSV export into a normalized DataFrame.

    Columns: date, ticker, type, quantity, price, amount, currency, fx_rate.
    Rows are sorted chronologically.
    """
    df = pd.read_csv(csv_path)
    df = df.rename(columns=_COLUMN_MAP)
    df["date"] = pd.to_datetime(df["date"])
    df["price"] = df["price"].apply(_parse_money)
    df["amount"] = df["amount"].apply(_parse_money)
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")
    df["fx_rate"] = pd.to_numeric(df["fx_rate"], errors="coerce")
    return df.sort_values("date").reset_index(drop=True)
