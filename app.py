"""revoscope — interactive dashboard for a Revolut investing portfolio.

Run with: streamlit run app.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from revoscope.parser import load_transactions
from revoscope.portfolio import build_positions, cash_balance
from revoscope.prices import ALL_SECTORS, get_live_prices, get_price_history, get_sectors

DEFAULT_CSV = Path(__file__).parent / "data" / "raw" / "transactions.csv"

st.set_page_config(page_title="revoscope", page_icon="📊", layout="wide")


@st.cache_data
def _load(csv_bytes_or_path):
    return load_transactions(csv_bytes_or_path)


def money(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def pct(value: float) -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"


def qty(value: float) -> str:
    return f"{value:,.2f}"


# ---------------------------------------------------------------- sidebar --
st.sidebar.title("📊 revoscope")
uploaded = st.sidebar.file_uploader("Upload a Revolut CSV export", type="csv")
if st.sidebar.button("🔄 Refresh live prices"):
    get_live_prices.clear()
    get_price_history.clear()

source = uploaded if uploaded is not None else DEFAULT_CSV
if uploaded is None and not DEFAULT_CSV.exists():
    st.info(
        "👋 **Upload your Revolut transactions CSV in the sidebar to get started.**\n\n"
        "In the Revolut app: **Invest → Statements → Export → CSV**, "
        "then upload the file here."
    )
    st.stop()

transactions = _load(source)

# --------------------------------------------------------------- compute --
positions = build_positions(transactions)
cash = cash_balance(transactions)
open_positions = {t: p for t, p in positions.items() if p.is_open}
closed_positions = {t: p for t, p in positions.items() if not p.is_open}

live_prices = get_live_prices(tuple(sorted(open_positions)))

rows = []
for ticker, pos in open_positions.items():
    current_price = live_prices.get(ticker, float("nan"))
    market_value = pos.quantity * current_price if pd.notna(current_price) else float("nan")
    unrealized = market_value - pos.cost_basis if pd.notna(market_value) else float("nan")
    unrealized_pct = (unrealized / pos.cost_basis * 100) if pos.cost_basis > 0 and pd.notna(unrealized) else float("nan")
    rows.append(
        {
            "Ticker": ticker,
            "Quantity": pos.quantity,
            "Avg Entry": pos.avg_price,
            "Current Price": current_price,
            "Market Value": market_value,
            "Unrealized P&L": unrealized,
            "Unrealized %": unrealized_pct,
            "Realized P&L": pos.realized_pnl,
            "Dividends": pos.dividends,
        }
    )
holdings_df = pd.DataFrame(rows).sort_values("Market Value", ascending=False).reset_index(drop=True)

total_market_value = holdings_df["Market Value"].sum(skipna=True)
total_cost_basis = sum(p.cost_basis for p in open_positions.values())
total_unrealized = total_market_value - total_cost_basis
total_realized = sum(p.realized_pnl for p in positions.values())
total_dividends = sum(p.dividends for p in positions.values())
account_value = total_market_value + cash

sectors = get_sectors(tuple(sorted(open_positions)))
sector_value = (
    holdings_df.assign(Sector=holdings_df["Ticker"].map(sectors)).groupby("Sector")["Market Value"].sum(min_count=1)
    if not holdings_df.empty
    else pd.Series(dtype=float)
)
all_sector_names = list(dict.fromkeys(ALL_SECTORS + [s for s in sector_value.index if s not in ALL_SECTORS]))
sector_df = pd.DataFrame({"Sector": all_sector_names})
sector_df["Amount"] = sector_df["Sector"].map(sector_value).fillna(0.0)
sector_df["Percentage"] = (sector_df["Amount"] / total_market_value * 100) if total_market_value else 0.0
sector_df = sector_df.sort_values("Amount", ascending=False).reset_index(drop=True)

# ------------------------------------------------------------------ tabs --
tab_overview, tab_detail, tab_transactions = st.tabs(["Overview", "Stock Detail", "Transactions"])

with tab_overview:
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Account Value", money(account_value))
    c2.metric("Unrealized P&L", money(total_unrealized), pct(total_unrealized / total_cost_basis * 100) if total_cost_basis else None)
    c3.metric("Realized P&L", money(total_realized))
    c4.metric("Dividends Received", money(total_dividends))
    c5.metric("Cash Balance", money(cash))

    st.subheader("Allocation")
    if not holdings_df.empty and holdings_df["Market Value"].notna().any():
        treemap_col, badge_col = st.columns([5, 1])

        with treemap_col:
            fig = px.treemap(
                holdings_df.dropna(subset=["Market Value"]),
                path=["Ticker"],
                values="Market Value",
                color="Unrealized %",
                color_continuous_scale="RdYlGn",
                color_continuous_midpoint=0,
            )
            fig.update_traces(
                texttemplate="%{label}<br>%{percentRoot:.0%}",
                hovertemplate="<b>%{label}</b><br>Market Value: $%{value:,.2f}<br>Allocation: %{percentRoot:.1%}<br>Unrealized: %{color:.2f}%<extra></extra>",
            )
            fig.update_layout(margin=dict(t=10, b=10, l=10, r=10))
            treemap_event = st.plotly_chart(fig, use_container_width=True, on_select="rerun", key="allocation_treemap")
            clicked = treemap_event.selection.points[0]["label"] if treemap_event and treemap_event.selection and treemap_event.selection.points else None
            if clicked and clicked != st.session_state.get("_last_treemap_ticker"):
                st.session_state["selected_ticker"] = clicked
            st.session_state["_last_treemap_ticker"] = clicked

        with badge_col:
            badge_ticker = st.session_state.get("selected_ticker")
            badge_row = holdings_df[holdings_df["Ticker"] == badge_ticker] if badge_ticker else pd.DataFrame()
            if not badge_row.empty:
                st.markdown(f"**{badge_ticker}**")
                st.metric("Unrealized P&L", money(badge_row["Unrealized P&L"].iloc[0]), pct(badge_row["Unrealized %"].iloc[0]))
    else:
        st.info("No live prices available yet for an allocation chart.")

    st.subheader("Sector Allocation")
    st.caption("Percentage of invested (non-cash) portfolio value per sector.")
    bar_fig = px.bar(
        sector_df,
        x="Amount",
        y="Sector",
        orientation="h",
        text=sector_df.apply(lambda r: f"${r['Amount']:,.2f} ({r['Percentage']:.1f}%)", axis=1),
    )
    bar_fig.update_traces(marker_color="#636EFA", textposition="outside")
    bar_fig.update_layout(margin=dict(t=10, b=10, l=10, r=120), xaxis_title="Market Value ($)", yaxis_title=None)
    bar_fig.update_yaxes(autorange="reversed")
    st.plotly_chart(bar_fig, use_container_width=True)

    sector_display = sector_df.copy()
    sector_display["Amount"] = sector_display["Amount"].map(money)
    sector_display["Percentage"] = sector_display["Percentage"].map(lambda v: f"{v:.2f}%")
    st.dataframe(sector_display, use_container_width=True, hide_index=True)

    st.subheader("Holdings")
    display_df = holdings_df.copy()
    for col in ["Avg Entry", "Current Price", "Market Value", "Unrealized P&L", "Realized P&L", "Dividends"]:
        display_df[col] = display_df[col].map(lambda v: money(v) if pd.notna(v) else "—")
    display_df["Unrealized %"] = holdings_df["Unrealized %"].map(lambda v: pct(v) if pd.notna(v) else "—")
    display_df["Quantity"] = holdings_df["Quantity"].map(qty)

    table_event = st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="holdings_table",
    )
    clicked = holdings_df.iloc[table_event.selection.rows[0]]["Ticker"] if table_event.selection.rows else None
    if clicked and clicked != st.session_state.get("_last_table_ticker"):
        st.session_state["selected_ticker"] = clicked
    st.session_state["_last_table_ticker"] = clicked

    if closed_positions:
        with st.expander(f"Closed positions ({len(closed_positions)})"):
            closed_df = pd.DataFrame(
                [
                    {"Ticker": t, "Realized P&L": money(p.realized_pnl), "Dividends": money(p.dividends)}
                    for t, p in closed_positions.items()
                ]
            )
            st.dataframe(closed_df, use_container_width=True, hide_index=True)

with tab_detail:
    all_tickers = sorted(positions.keys())
    if st.session_state.get("selected_ticker") not in all_tickers:
        st.session_state["selected_ticker"] = all_tickers[0] if all_tickers else None

    # Bound to the same session_state key that the Overview tab's treemap/table
    # click handlers write to, so a click there drives this selectbox too.
    selected = st.selectbox("Stock", all_tickers, key="selected_ticker")

    if selected:
        pos = positions[selected]
        current_price = live_prices.get(selected, float("nan"))
        market_value = pos.quantity * current_price if pos.is_open and pd.notna(current_price) else float("nan")
        unrealized = market_value - pos.cost_basis if pd.notna(market_value) else float("nan")
        unrealized_pct = (unrealized / pos.cost_basis * 100) if pos.cost_basis > 0 and pd.notna(unrealized) else float("nan")
        realized_pct = (pos.realized_pnl / pos.cost_basis_sold * 100) if pos.cost_basis_sold > 0 else float("nan")

        d1, d2, d3, d4, d5 = st.columns(5)
        d1.metric("Quantity Held", qty(pos.quantity))
        d2.metric("Avg Entry Price", money(pos.avg_price) if pos.is_open else "—")
        d3.metric("Current Price", money(current_price) if pd.notna(current_price) else "—")
        d4.metric("Unrealized P&L", money(unrealized) if pd.notna(unrealized) else "—", pct(unrealized_pct) if pd.notna(unrealized_pct) else None)
        d5.metric("Realized P&L", money(pos.realized_pnl), pct(realized_pct) if pd.notna(realized_pct) else None)
        st.caption(f"Dividends received: {money(pos.dividends)}")

        unrealized_pct_total = (unrealized / pos.total_invested * 100) if pos.total_invested > 0 and pd.notna(unrealized) else float("nan")
        realized_pct_total = (pos.realized_pnl / pos.total_invested * 100) if pos.total_invested > 0 else float("nan")

        st.subheader("Capital invested")
        st.caption("Unrealized/Realized % here are both against total capital ever invested in this stock.")
        i1, i2, i3, i4 = st.columns(4)
        i1.metric("Total Invested (all-time)", money(pos.total_invested))
        i2.metric("Currently Invested", money(pos.cost_basis))
        i3.metric("Unrealized P&L", money(unrealized) if pd.notna(unrealized) else "—", pct(unrealized_pct_total) if pd.notna(unrealized_pct_total) else None)
        i4.metric("Realized P&L", money(pos.realized_pnl), pct(realized_pct_total) if pd.notna(realized_pct_total) else None)

        st.subheader(f"{selected} price history with your trades")
        history = get_price_history(selected)
        if not history.empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=history["Date"], y=history["Close"], mode="lines", name="Close price", line=dict(color="#636EFA")))
            buys = pos.trades[pos.trades["type"] == "BUY - MARKET"] if not pos.trades.empty else pd.DataFrame()
            sells = pos.trades[pos.trades["type"] == "SELL - MARKET"] if not pos.trades.empty else pd.DataFrame()
            if not buys.empty:
                fig.add_trace(go.Scatter(x=buys["date"], y=buys["price"], mode="markers", name="Buy", marker=dict(color="green", size=10, symbol="triangle-up")))
            if not sells.empty:
                fig.add_trace(go.Scatter(x=sells["date"], y=sells["price"], mode="markers", name="Sell", marker=dict(color="red", size=10, symbol="triangle-down")))
            fig.update_layout(margin=dict(t=10, b=10, l=10, r=10), legend=dict(orientation="h"))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No price history available for this ticker.")

        st.subheader("Trade history")
        if not pos.trades.empty:
            trades_display = pos.trades.copy()
            trades_display["date"] = trades_display["date"].dt.strftime("%Y-%m-%d %H:%M")
            trades_display["price"] = trades_display["price"].map(lambda v: money(v) if pd.notna(v) else "—")
            trades_display["amount"] = trades_display["amount"].map(money)
            trades_display["quantity"] = trades_display["quantity"].map(lambda v: qty(v) if pd.notna(v) else "—")
            st.dataframe(
                trades_display[["date", "type", "quantity", "price", "amount"]].rename(
                    columns={"date": "Date", "type": "Type", "quantity": "Quantity", "price": "Price", "amount": "Amount"}
                ),
                use_container_width=True,
                hide_index=True,
            )

with tab_transactions:
    st.subheader("Full transaction log")
    type_filter = st.multiselect("Filter by type", sorted(transactions["type"].unique()))
    ticker_filter = st.multiselect("Filter by ticker", sorted(transactions["ticker"].dropna().unique()))

    log = transactions.copy()
    if type_filter:
        log = log[log["type"].isin(type_filter)]
    if ticker_filter:
        log = log[log["ticker"].isin(ticker_filter)]

    log_display = log.copy()
    log_display["date"] = log_display["date"].dt.strftime("%Y-%m-%d %H:%M")
    log_display["price"] = log_display["price"].map(lambda v: money(v) if pd.notna(v) else "—")
    log_display["amount"] = log_display["amount"].map(money)
    log_display["quantity"] = log_display["quantity"].map(lambda v: qty(v) if pd.notna(v) else "—")
    st.dataframe(
        log_display[["date", "ticker", "type", "quantity", "price", "amount", "currency"]].rename(
            columns={"date": "Date", "ticker": "Ticker", "type": "Type", "quantity": "Quantity", "price": "Price", "amount": "Amount", "currency": "Currency"}
        ),
        use_container_width=True,
        hide_index=True,
    )
