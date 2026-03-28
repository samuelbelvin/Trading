from __future__ import annotations
from datetime import datetime
import pandas as pd
import streamlit as st

from config import settings
from execution.base import OrderRequest
from execution.paper import PaperBroker
from execution.alpaca_live import AlpacaLiveBroker
from execution.oanda_live import OandaLiveBroker
from services.market_data import fetch_multi_asset_rows
from services.risk import check_risk
from services.signals import tradable_rows, trade_side_from_row

st.set_page_config(page_title="Final Multi-Asset Trading Platform", layout="wide")

if "paper_broker" not in st.session_state:
    st.session_state.paper_broker = PaperBroker()
if "orders" not in st.session_state:
    st.session_state.orders = []
if "errors" not in st.session_state:
    st.session_state.errors = []
if "realized_daily_pnl_pct" not in st.session_state:
    st.session_state.realized_daily_pnl_pct = 0.0

alpaca = AlpacaLiveBroker(settings.alpaca_api_key, settings.alpaca_api_secret, settings.alpaca_base_url)
oanda = OandaLiveBroker(settings.oanda_api_key, settings.oanda_account_id, settings.oanda_env)

def get_broker(asset_class: str):
    if settings.trading_mode == "paper":
        return st.session_state.paper_broker
    if asset_class == "forex" and settings.forex_execution_broker.lower() == "oanda":
        return oanda
    if asset_class in {"stock", "crypto"} and (
        (asset_class == "stock" and settings.stock_execution_broker.lower() == "alpaca") or
        (asset_class == "crypto" and settings.crypto_execution_broker.lower() == "alpaca")
    ):
        return alpaca
    return st.session_state.paper_broker

@st.cache_data(ttl=settings.poll_seconds, show_spinner=False)
def cached_market_rows():
    return fetch_multi_asset_rows()

st.title("Final Multi-Asset Trading Platform")
st.caption("Forex through OANDA. Stocks and crypto through Alpaca. Paper mode is still the safest place to start.")

left, right = st.columns([1, 3])
with left:
    if st.button("Refresh market data", use_container_width=True):
        cached_market_rows.clear()
        st.rerun()
with right:
    st.write(
        f"Mode: {settings.trading_mode.upper()} | "
        f"Forex: {settings.forex_execution_broker.upper()} | "
        f"Stocks: {settings.stock_execution_broker.upper()} | "
        f"Crypto: {settings.crypto_execution_broker.upper()} | "
        f"Poll TTL: {settings.poll_seconds}s"
    )

rows, fetch_errors = cached_market_rows()
st.session_state.errors = fetch_errors + st.session_state.errors
tradable = tradable_rows(rows, min_score=70)
rows_df = pd.DataFrame(rows)

alpaca_account = alpaca.get_account()
oanda_account = oanda.get_account() if settings.trading_mode != "paper" else {"broker": "oanda", "status": "paper_mode"}

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Rows", len(rows))
c2.metric("Tradable setups", len(tradable))
c3.metric("Paper positions", len(st.session_state.paper_broker.get_positions()))
c4.metric("Daily PnL %", f"{st.session_state.realized_daily_pnl_pct*100:.2f}%")
c5.metric("Mode", settings.trading_mode.upper())

with st.expander("Broker readiness"):
    readiness = pd.DataFrame([
        {"item": "Alpaca configured", "value": alpaca.configured()},
        {"item": "OANDA configured", "value": oanda.configured()},
        {"item": "Polygon configured", "value": bool(settings.polygon_api_key)},
        {"item": "Forex live capable", "value": settings.trading_mode != "paper" and oanda.configured()},
        {"item": "Stock live capable", "value": settings.trading_mode != "paper" and alpaca.configured()},
        {"item": "Crypto live capable", "value": settings.trading_mode != "paper" and alpaca.configured()},
        {"item": "Kill switch", "value": settings.kill_switch},
    ])
    st.dataframe(readiness, use_container_width=True, hide_index=True)
    st.write("Alpaca account:")
    st.json(alpaca_account)
    st.write("OANDA account:")
    st.json(oanda_account)

st.markdown("### Market opportunities")
if rows_df.empty:
    rows_df = pd.DataFrame(columns=["asset_class", "symbol", "price", "change_pct", "score", "signal", "bias", "updated"])
st.dataframe(rows_df, use_container_width=True, hide_index=True)

st.markdown("### Trade launcher")
a, b, c, d, e = st.columns(5)
asset_class = a.selectbox("Asset class", ["forex", "stock", "crypto"])
symbol_options = {
    "stock": settings.stock_symbols,
    "forex": settings.forex_symbols,
    "crypto": settings.crypto_symbols,
}
symbol = b.selectbox("Symbol", symbol_options[asset_class])
side = c.selectbox("Side", ["buy", "sell"])
notional = d.number_input("Notional USD / proxy", min_value=10.0, value=float(settings.default_order_size_usd), step=10.0)
qty = e.number_input("Units / Qty (optional)", min_value=0.0, value=0.0, step=1.0)

if st.button("Submit order", type="primary"):
    order = OrderRequest(
        asset_class=asset_class,
        symbol=symbol,
        side=side,
        notional_usd=float(notional),
        qty=float(qty) if qty > 0 else None,
    )
    broker = get_broker(asset_class)
    open_positions = st.session_state.paper_broker.get_positions()
    try:
        if settings.trading_mode != "paper":
            if asset_class == "forex" and oanda.configured():
                open_positions = oanda.get_positions()
            elif asset_class in {"stock", "crypto"} and alpaca.configured():
                open_positions = alpaca.get_positions()
    except Exception:
        pass

    ok, message = check_risk(order, open_positions, st.session_state.realized_daily_pnl_pct)
    if not ok:
        st.error(message)
    else:
        result = broker.place_order(order)
        st.session_state.orders.insert(0, {
            "ts": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "asset_class": asset_class,
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "notional_usd": notional,
            "broker": result.broker,
            "status": result.status,
            "message": result.message,
        })
        if result.ok:
            st.success(f"Order accepted by {result.broker}: {result.message}")
        else:
            st.warning(f"{result.broker} response: {result.message}")

st.markdown("### One-click trade from top setups")
if tradable:
    for row in tradable[:5]:
        cols = st.columns([2, 1, 1, 1])
        cols[0].write(f"{row['symbol']} ({row['asset_class']}) — {row['signal']} — score {row['score']}")
        cols[1].write(row["bias"])
        cols[2].write(f"{row['price']}")
        action = trade_side_from_row(row)
        if cols[3].button(f"{action.title()} {row['symbol']}", key=f"quick-{row['asset_class']}-{row['symbol']}"):
            order = OrderRequest(
                asset_class=row["asset_class"],
                symbol=row["symbol"],
                side=action,
                notional_usd=float(settings.default_order_size_usd),
            )
            broker = get_broker(row["asset_class"])
            result = broker.place_order(order)
            st.session_state.orders.insert(0, {
                "ts": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                "asset_class": row["asset_class"],
                "symbol": row["symbol"],
                "side": action,
                "qty": "",
                "notional_usd": settings.default_order_size_usd,
                "broker": result.broker,
                "status": result.status,
                "message": result.message,
            })
            if result.ok:
                st.success(f"{row['symbol']}: order submitted via {result.broker}.")
            else:
                st.warning(f"{row['symbol']}: {result.message}")
else:
    st.info("No setups above the current tradable threshold.")

st.markdown("### Orders")
orders_df = pd.DataFrame(st.session_state.orders)
if orders_df.empty:
    orders_df = pd.DataFrame(columns=["ts", "asset_class", "symbol", "side", "qty", "notional_usd", "broker", "status", "message"])
st.dataframe(orders_df, use_container_width=True, hide_index=True)

st.markdown("### Paper positions")
paper_df = pd.DataFrame(st.session_state.paper_broker.get_positions())
if paper_df.empty:
    paper_df = pd.DataFrame(columns=["symbol", "qty", "asset_class"])
st.dataframe(paper_df, use_container_width=True, hide_index=True)

if settings.trading_mode != "paper":
    st.markdown("### Live positions")
    live_stock_crypto = pd.DataFrame(alpaca.get_positions())
    live_forex = pd.DataFrame(oanda.get_positions()) if oanda.configured() else pd.DataFrame()
    if live_stock_crypto.empty:
        live_stock_crypto = pd.DataFrame(columns=["symbol", "asset_class", "qty", "side", "market_value", "unrealized_pl"])
    if live_forex.empty:
        live_forex = pd.DataFrame(columns=["symbol", "asset_class", "long_units", "short_units", "pl"])
    st.write("Alpaca positions")
    st.dataframe(live_stock_crypto, use_container_width=True, hide_index=True)
    st.write("OANDA positions")
    st.dataframe(live_forex, use_container_width=True, hide_index=True)

if st.session_state.errors:
    st.markdown("### Diagnostics")
    seen = []
    for err in st.session_state.errors:
        if err not in seen:
            st.code(err)
            seen.append(err)
        if len(seen) >= 10:
            break

st.markdown("### Notes")
st.write("- Forex execution routes to OANDA.")
st.write("- Stock and crypto execution route to Alpaca.")
st.write("- Stocks can also use Polygon snapshots for scanner rows when POLYGON_API_KEY is set.")
st.write("- Start in paper mode even after all credentials are entered.")
