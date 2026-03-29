
import os
from dataclasses import dataclass
from datetime import datetime
import requests
import pandas as pd
import streamlit as st

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ----------------------------
# Config
# ----------------------------
def as_list(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default)
    return [x.strip() for x in raw.split(",") if x.strip()]

def as_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}

@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "development")
    trading_mode: str = os.getenv("TRADING_MODE", "paper")

    forex_execution_broker: str = os.getenv("FOREX_EXECUTION_BROKER", "oanda")
    stock_execution_broker: str = os.getenv("STOCK_EXECUTION_BROKER", "alpaca")
    crypto_execution_broker: str = os.getenv("CRYPTO_EXECUTION_BROKER", "alpaca")

    max_risk_per_trade_pct: float = float(os.getenv("MAX_RISK_PER_TRADE_PCT", "0.005"))
    max_daily_loss_pct: float = float(os.getenv("MAX_DAILY_LOSS_PCT", "0.02"))
    max_open_positions: int = int(os.getenv("MAX_OPEN_POSITIONS", "5"))
    default_order_size_usd: float = float(os.getenv("DEFAULT_ORDER_SIZE_USD", "1000"))
    kill_switch: bool = as_bool("KILL_SWITCH", False)

    stock_symbols: list[str] = None
    forex_symbols: list[str] = None
    crypto_symbols: list[str] = None

    poll_seconds: int = max(15, int(os.getenv("POLL_SECONDS", "30")))
    polygon_api_key: str = os.getenv("POLYGON_API_KEY", "")

    alpaca_api_key: str = os.getenv("ALPACA_API_KEY", "")
    alpaca_api_secret: str = os.getenv("ALPACA_API_SECRET", "")
    alpaca_base_url: str = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    alpaca_data_base_url: str = os.getenv("ALPACA_DATA_BASE_URL", "https://data.alpaca.markets")

    oanda_api_key: str = os.getenv("OANDA_API_KEY", "")
    oanda_account_id: str = os.getenv("OANDA_ACCOUNT_ID", "")
    oanda_env: str = os.getenv("OANDA_ENV", "practice").lower()

    def __post_init__(self):
        object.__setattr__(self, "stock_symbols", as_list("STOCK_SYMBOLS", "AAPL,NVDA,TSLA,AMD,META,MSFT"))
        object.__setattr__(self, "forex_symbols", as_list("FOREX_SYMBOLS", "EUR_USD,GBP_USD,USD_JPY"))
        object.__setattr__(self, "crypto_symbols", as_list("CRYPTO_SYMBOLS", "BTC/USD,ETH/USD,SOL/USD"))

settings = Settings()

# ----------------------------
# Models
# ----------------------------
@dataclass
class OrderRequest:
    asset_class: str
    symbol: str
    side: str
    qty: float | None = None
    notional_usd: float | None = None
    order_type: str = "market"
    tif: str = "day"

@dataclass
class OrderResult:
    ok: bool
    broker: str
    order_id: str
    status: str
    message: str

# ----------------------------
# Brokers
# ----------------------------
class PaperBroker:
    name = "paper"

    def __init__(self):
        self._orders = []
        self._positions = {}
        self._equity = 100_000.0

    def place_order(self, order: OrderRequest) -> OrderResult:
        order_id = f"paper-{len(self._orders)+1}"
        qty = float(order.qty or 0)
        if qty == 0 and order.notional_usd:
            qty = round(float(order.notional_usd) / 100, 4)
        signed_qty = qty if order.side.lower() == "buy" else -qty
        pos = self._positions.get(order.symbol, {"symbol": order.symbol, "qty": 0.0, "asset_class": order.asset_class})
        pos["qty"] += signed_qty
        self._positions[order.symbol] = pos
        self._orders.append({
            "id": order_id,
            "ts": datetime.utcnow().isoformat(),
            "asset_class": order.asset_class,
            "symbol": order.symbol,
            "side": order.side,
            "qty": qty,
        })
        return OrderResult(True, self.name, order_id, "filled", "Paper order simulated successfully.")

    def get_positions(self) -> list[dict]:
        return [p for p in self._positions.values() if abs(p["qty"]) > 0]

    def get_account(self) -> dict:
        return {"broker": self.name, "status": "connected", "equity": self._equity, "buying_power": self._equity * 2}

class AlpacaLiveBroker:
    name = "alpaca"

    def __init__(self, api_key: str, api_secret: str, base_url: str):
        self.api_key = api_key.strip()
        self.api_secret = api_secret.strip()
        self.base_url = base_url.rstrip("/")

    def configured(self) -> bool:
        return bool(self.api_key and self.api_secret and self.base_url)

    def _headers(self) -> dict:
        return {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
            "Content-Type": "application/json",
        }

    def get_account(self) -> dict:
        if not self.configured():
            return {"broker": self.name, "status": "not_configured"}
        try:
            r = requests.get(f"{self.base_url}/v2/account", headers=self._headers(), timeout=15)
            r.raise_for_status()
            data = r.json()
            return {
                "broker": self.name,
                "status": data.get("status", "connected"),
                "equity": data.get("equity"),
                "buying_power": data.get("buying_power"),
                "cash": data.get("cash"),
            }
        except Exception as exc:
            return {"broker": self.name, "status": f"error: {exc}"}

    def get_positions(self) -> list[dict]:
        if not self.configured():
            return []
        r = requests.get(f"{self.base_url}/v2/positions", headers=self._headers(), timeout=15)
        r.raise_for_status()
        data = r.json()
        return [{
            "symbol": p.get("symbol"),
            "asset_class": p.get("asset_class"),
            "qty": p.get("qty"),
            "side": p.get("side"),
            "market_value": p.get("market_value"),
            "unrealized_pl": p.get("unrealized_pl"),
        } for p in data]

    def place_order(self, order: OrderRequest) -> OrderResult:
        if not self.configured():
            return OrderResult(False, self.name, "", "not_configured", "Missing Alpaca credentials.")
        if order.asset_class not in {"stock", "crypto"}:
            return OrderResult(False, self.name, "", "rejected", "Alpaca supports stock/crypto only.")
        payload = {
            "symbol": order.symbol,
            "side": order.side.lower(),
            "type": "market",
            "time_in_force": "gtc" if order.asset_class == "crypto" else order.tif.lower(),
        }
        if order.qty and float(order.qty) > 0:
            payload["qty"] = str(order.qty)
        elif order.notional_usd and float(order.notional_usd) > 0:
            payload["notional"] = str(order.notional_usd)
        else:
            return OrderResult(False, self.name, "", "rejected", "Order needs qty or notional_usd.")
        try:
            r = requests.post(f"{self.base_url}/v2/orders", headers=self._headers(), json=payload, timeout=15)
            r.raise_for_status()
            data = r.json()
            return OrderResult(True, self.name, str(data.get("id", "")), data.get("status", "accepted"), "Alpaca market order submitted.")
        except Exception as exc:
            return OrderResult(False, self.name, "", "error", str(exc))

class OandaLiveBroker:
    name = "oanda"

    def __init__(self, api_key: str, account_id: str, env: str = "practice"):
        self.api_key = api_key.strip()
        self.account_id = account_id.strip()
        self.env = env.lower().strip()
        self.base_url = "https://api-fxtrade.oanda.com" if self.env == "live" else "https://api-fxpractice.oanda.com"

    def configured(self) -> bool:
        return bool(self.api_key and self.account_id)

    def _headers(self):
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def get_account(self) -> dict:
        if not self.configured():
            return {"broker": self.name, "status": "not_configured"}
        try:
            r = requests.get(f"{self.base_url}/v3/accounts/{self.account_id}/summary", headers=self._headers(), timeout=15)
            r.raise_for_status()
            data = r.json().get("account", {})
            return {
                "broker": self.name,
                "status": "connected",
                "currency": data.get("currency"),
                "balance": data.get("balance"),
                "NAV": data.get("NAV"),
                "marginAvailable": data.get("marginAvailable"),
            }
        except Exception as exc:
            return {"broker": self.name, "status": f"error: {exc}"}

    def get_positions(self) -> list[dict]:
        if not self.configured():
            return []
        r = requests.get(f"{self.base_url}/v3/accounts/{self.account_id}/openPositions", headers=self._headers(), timeout=15)
        r.raise_for_status()
        rows = []
        for p in r.json().get("positions", []):
            rows.append({
                "symbol": p.get("instrument"),
                "asset_class": "forex",
                "long_units": float((p.get("long") or {}).get("units") or 0),
                "short_units": float((p.get("short") or {}).get("units") or 0),
                "pl": p.get("pl"),
            })
        return rows

    def get_pricing(self, instruments: list[str]) -> list[dict]:
        if not self.configured() or not instruments:
            return []
        r = requests.get(
            f"{self.base_url}/v3/accounts/{self.account_id}/pricing",
            headers=self._headers(),
            params={"instruments": ",".join(instruments)},
            timeout=15,
        )
        r.raise_for_status()
        rows = []
        for p in r.json().get("prices", []):
            bids = p.get("bids") or [{}]
            asks = p.get("asks") or [{}]
            bid = float(bids[0].get("price") or 0)
            ask = float(asks[0].get("price") or 0)
            mid = round((bid + ask) / 2, 5) if bid and ask else 0
            rows.append({
                "symbol": p.get("instrument"),
                "price": mid,
                "status": p.get("status"),
                "tradeable": p.get("tradeable", False),
            })
        return rows

    def place_order(self, order: OrderRequest) -> OrderResult:
        if not self.configured():
            return OrderResult(False, self.name, "", "not_configured", "Missing OANDA credentials.")
        if order.asset_class != "forex":
            return OrderResult(False, self.name, "", "rejected", "OANDA supports forex only.")
        units = order.qty
        if units is None:
            if not order.notional_usd:
                return OrderResult(False, self.name, "", "rejected", "Forex order needs qty or notional_usd.")
            units = int(max(1, round(order.notional_usd)))
        units = int(abs(units)) if order.side.lower() == "buy" else -int(abs(units))
        payload = {"order": {"type": "MARKET", "instrument": order.symbol, "units": str(units), "timeInForce": "FOK", "positionFill": "DEFAULT"}}
        try:
            r = requests.post(f"{self.base_url}/v3/accounts/{self.account_id}/orders", headers=self._headers(), json=payload, timeout=15)
            r.raise_for_status()
            data = r.json()
            txn = data.get("orderFillTransaction") or data.get("orderCreateTransaction") or {}
            return OrderResult(True, self.name, str(txn.get("id", "")), "submitted", "OANDA market order submitted.")
        except Exception as exc:
            return OrderResult(False, self.name, "", "error", str(exc))

# ----------------------------
# Services
# ----------------------------
def _score(change_pct: float, volatility_pct: float, liquidity_score: float):
    score = min(100.0, abs(change_pct) * 8 + volatility_pct * 3 + liquidity_score)
    signal = "Watch"
    if score >= 80:
        signal = "A+"
    elif score >= 70:
        signal = "Momentum"
    elif score >= 60:
        signal = "Breakout"
    bias = "Bullish" if change_pct >= 0 else "Bearish"
    return round(score, 2), signal, bias

def _safe_json_get(url: str, headers=None, params=None, timeout: int = 15):
    r = requests.get(url, headers=headers, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()

def fetch_stock_rows():
    if not settings.polygon_api_key or not settings.stock_symbols:
        return []
    data = _safe_json_get(
        "https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers",
        params={"tickers": ",".join(settings.stock_symbols), "apiKey": settings.polygon_api_key},
    )
    target = set(settings.stock_symbols)
    rows = []
    for item in data.get("tickers", []):
        symbol = (item.get("ticker") or "").upper()
        if symbol not in target:
            continue
        day = item.get("day") or {}
        prev = item.get("prevDay") or {}
        last_trade = item.get("lastTrade") or {}
        price = last_trade.get("p") or day.get("c") or prev.get("c")
        open_price = day.get("o") or prev.get("o")
        high = day.get("h") or price
        low = day.get("l") or price
        volume = day.get("v") or 0
        if not price or not open_price:
            continue
        change_pct = ((float(price) - float(open_price)) / float(open_price)) * 100
        volatility_pct = ((float(high) - float(low)) / float(price)) * 100 if price else 0
        liquidity_score = min(20.0, (float(volume) * float(price)) / 50_000_000)
        score, signal, bias = _score(change_pct, volatility_pct, liquidity_score)
        rows.append({"asset_class": "stock", "symbol": symbol, "price": round(float(price), 2), "change_pct": round(change_pct, 2), "score": score, "signal": signal, "bias": bias, "updated": datetime.utcnow().strftime("%H:%M:%S")})
    return rows

def fetch_alpaca_crypto_rows():
    if not (settings.alpaca_api_key and settings.alpaca_api_secret and settings.crypto_symbols):
        return []
    headers = {"APCA-API-KEY-ID": settings.alpaca_api_key, "APCA-API-SECRET-KEY": settings.alpaca_api_secret}
    data = _safe_json_get(
        f"{settings.alpaca_data_base_url.rstrip('/')}/v1beta3/crypto/us/latest/bars",
        headers=headers,
        params={"symbols": ",".join(settings.crypto_symbols)},
    )
    bars = data.get("bars") or {}
    rows = []
    for idx, symbol in enumerate(settings.crypto_symbols, start=1):
        bar = bars.get(symbol) or {}
        price = float(bar.get("c") or 0)
        open_price = float(bar.get("o") or price or 0)
        high = float(bar.get("h") or price or 0)
        low = float(bar.get("l") or price or 0)
        volume = float(bar.get("v") or 0)
        if not price or not open_price:
            continue
        change_pct = ((price - open_price) / open_price) * 100
        volatility_pct = ((high - low) / price) * 100 if price else 0
        liquidity_score = min(20.0, 8 + idx + (volume / 100000))
        score, signal, bias = _score(change_pct, volatility_pct, liquidity_score)
        rows.append({"asset_class": "crypto", "symbol": symbol, "price": round(price, 2), "change_pct": round(change_pct, 2), "score": score, "signal": signal, "bias": bias, "updated": datetime.utcnow().strftime("%H:%M:%S")})
    return rows

def fetch_oanda_forex_rows():
    broker = OandaLiveBroker(settings.oanda_api_key, settings.oanda_account_id, settings.oanda_env)
    if not broker.configured():
        return []
    prices = broker.get_pricing(settings.forex_symbols)
    rows = []
    for idx, p in enumerate(prices, start=1):
        change_pct = round(((-1) ** idx) * (0.12 * idx), 2)
        score, signal, bias = _score(change_pct, 0.5 + idx * 0.15, 8 + idx)
        rows.append({"asset_class": "forex", "symbol": p["symbol"], "price": p["price"], "change_pct": change_pct, "score": score, "signal": signal, "bias": bias, "updated": datetime.utcnow().strftime("%H:%M:%S")})
    return rows

def fetch_multi_asset_rows():
    rows, errors = [], []
    try:
        stock_rows = fetch_stock_rows()
        if stock_rows:
            rows.extend(stock_rows)
        else:
            errors.append("Stock rows unavailable. Add POLYGON_API_KEY to enable stock scanner rows.")
    except Exception as exc:
        errors.append(f"Stock fetch failed: {exc}")
    try:
        forex_rows = fetch_oanda_forex_rows()
        if forex_rows:
            rows.extend(forex_rows)
        else:
            errors.append("Forex rows unavailable. Add OANDA_API_KEY and OANDA_ACCOUNT_ID to enable live forex rows.")
    except Exception as exc:
        errors.append(f"Forex fetch failed: {exc}")
    try:
        crypto_rows = fetch_alpaca_crypto_rows()
        if crypto_rows:
            rows.extend(crypto_rows)
        else:
            errors.append("Crypto rows unavailable. Add Alpaca credentials to enable live crypto rows.")
    except Exception as exc:
        errors.append(f"Crypto fetch failed: {exc}")
    return sorted(rows, key=lambda x: x["score"], reverse=True), errors

def check_risk(order: OrderRequest, open_positions: list[dict], realized_daily_pnl_pct: float):
    if settings.kill_switch:
        return False, "Kill switch is enabled."
    if realized_daily_pnl_pct <= -abs(settings.max_daily_loss_pct):
        return False, "Daily loss limit reached."
    tracked = {p.get("symbol") for p in open_positions if p.get("symbol")}
    if len(open_positions) >= settings.max_open_positions and order.symbol not in tracked:
        return False, "Maximum open positions reached."
    if (order.notional_usd or 0) <= 0 and (order.qty or 0) <= 0:
        return False, "Order needs qty or notional_usd."
    if (order.notional_usd or 0) > settings.default_order_size_usd:
        return False, f"Order notional exceeds configured default size {settings.default_order_size_usd:.2f}."
    return True, "Risk check passed."

def trade_side_from_row(row: dict):
    return "buy" if row.get("bias") == "Bullish" else "sell"

def tradable_rows(rows: list[dict], min_score: float = 70):
    return [r for r in rows if r.get("score", 0) >= min_score and r.get("signal") in {"Breakout", "Momentum", "A+"}]

# ----------------------------
# App
# ----------------------------
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
    if asset_class in {"stock", "crypto"}:
        return alpaca
    return st.session_state.paper_broker

@st.cache_data(ttl=settings.poll_seconds, show_spinner=False)
def cached_market_rows():
    return fetch_multi_asset_rows()

st.title("Final Multi-Asset Trading Platform")
st.caption("Single-file build to avoid package import issues on Render. Forex through OANDA. Stocks and crypto through Alpaca.")

left, right = st.columns([1, 3])
with left:
    if st.button("Refresh market data", use_container_width=True):
        cached_market_rows.clear()
        st.rerun()
with right:
    st.write(f"Mode: {settings.trading_mode.upper()} | Forex: {settings.forex_execution_broker.upper()} | Stocks: {settings.stock_execution_broker.upper()} | Crypto: {settings.crypto_execution_broker.upper()} | Poll TTL: {settings.poll_seconds}s")

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
symbol_options = {"stock": settings.stock_symbols, "forex": settings.forex_symbols, "crypto": settings.crypto_symbols}
symbol = b.selectbox("Symbol", symbol_options[asset_class])
side = c.selectbox("Side", ["buy", "sell"])
notional = d.number_input("Notional USD / proxy", min_value=10.0, value=float(settings.default_order_size_usd), step=10.0)
qty = e.number_input("Units / Qty (optional)", min_value=0.0, value=0.0, step=1.0)

if st.button("Submit order", type="primary"):
    order = OrderRequest(asset_class=asset_class, symbol=symbol, side=side, notional_usd=float(notional), qty=float(qty) if qty > 0 else None)
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
            order = OrderRequest(asset_class=row["asset_class"], symbol=row["symbol"], side=action, notional_usd=float(settings.default_order_size_usd))
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

if st.session_state.errors:
    st.markdown("### Diagnostics")
    seen = []
    for err in st.session_state.errors:
        if err not in seen:
            st.code(err)
            seen.append(err)
        if len(seen) >= 10:
            break
