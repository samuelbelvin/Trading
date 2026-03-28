import os
import time
import math
import threading
from datetime import datetime, timedelta, timezone

import requests
import pandas as pd
import streamlit as st

# Optional Twilio support
try:
    from twilio.rest import Client
except Exception:
    Client = None

st.set_page_config(page_title="Trading Dashboard", layout="wide")

BINANCE_SYMBOLS = [s.strip().upper() for s in os.getenv("BINANCE_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT").split(",") if s.strip()]
POLYGON_STOCKS = [s.strip().upper() for s in os.getenv("POLYGON_STOCKS", "AAPL,NVDA,TSLA,AMD,META,MSFT").split(",") if s.strip()]
POLYGON_FOREX = [s.strip().upper() for s in os.getenv("POLYGON_FOREX", "C:EURUSD,C:GBPUSD,C:USDJPY").split(",") if s.strip()]
POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM = os.getenv("TWILIO_FROM", "")
TWILIO_TO = os.getenv("TWILIO_TO", "")

POLL_SECONDS = int(os.getenv("POLL_SECONDS", "15"))
ALERT_THRESHOLD = float(os.getenv("ALERT_THRESHOLD", "70"))
ALERT_COOLDOWN_MINUTES = int(os.getenv("ALERT_COOLDOWN_MINUTES", "20"))

twilio_client = None
if Client and all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM, TWILIO_TO]):
    try:
        twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    except Exception:
        twilio_client = None

state = {
    "rows": [],
    "last_update": None,
    "status": "starting",
    "errors": [],
    "last_alerts": {},
    "last_scores": {},
    "thread_started": False,
}
state_lock = threading.Lock()

def log_error(msg: str):
    with state_lock:
        state["errors"] = ([f"{datetime.now().strftime('%H:%M:%S')} - {msg}"] + state["errors"])[:10]

def safe_get_json(url: str, timeout: int = 12):
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()

def send_sms(message: str):
    if not twilio_client:
        return False, "Twilio not configured"
    try:
        twilio_client.messages.create(body=message, from_=TWILIO_FROM, to=TWILIO_TO)
        return True, "sent"
    except Exception as e:
        return False, str(e)

def clamp(val, low, high):
    return max(low, min(high, val))

def score_row(asset_class, symbol, price, change_pct, rvol, range_pct, above_vwap, breakout, dollar_vol_m):
    # Balanced profile:
    # threshold ~70, moderate alert flow, not ultra-strict
    score = 0.0
    score += clamp(abs(change_pct) * 4, 0, 20)      # momentum
    score += clamp(rvol * 12, 0, 24)                # participation
    score += clamp(range_pct * 3.5, 0, 18)          # intraday expansion
    score += clamp(dollar_vol_m / 50, 0, 18)        # liquidity
    score += 10 if above_vwap else 0                # bias
    score += 10 if breakout else 0                  # structure

    signal = "Watch"
    if score >= 80:
        signal = "A+"
    elif score >= 70:
        signal = "Momentum"
    elif score >= 60:
        signal = "Breakout"

    direction = "Bullish" if change_pct >= 0 else "Bearish"
    return round(score, 2), signal, direction

def should_alert(symbol, score, signal):
    now = datetime.now(timezone.utc)
    with state_lock:
        prev_score = state["last_scores"].get(symbol, 0)
        last_alert_iso = state["last_alerts"].get(symbol)

    if signal not in {"Momentum", "A+"}:
        return False

    if score < ALERT_THRESHOLD:
        return False

    if score - prev_score < 6 and prev_score >= ALERT_THRESHOLD:
        return False

    if last_alert_iso:
        last_alert = datetime.fromisoformat(last_alert_iso)
        if now - last_alert < timedelta(minutes=ALERT_COOLDOWN_MINUTES):
            return False

    return True

def mark_alert(symbol, score):
    now = datetime.now(timezone.utc).isoformat()
    with state_lock:
        state["last_alerts"][symbol] = now
        state["last_scores"][symbol] = score

def update_score(symbol, score):
    with state_lock:
        state["last_scores"][symbol] = score

def scan_binance():
    rows = []
    if not BINANCE_SYMBOLS:
        return rows

    try:
        tickers = safe_get_json("https://api.binance.com/api/v3/ticker/24hr")
    except Exception as e:
        log_error(f"Binance blocked: {e}")
        return rows  # <-- THIS IS THE FIX

    ticker_map = {t["symbol"]: t for t in tickers if t.get("symbol") in BINANCE_SYMBOLS}

    for symbol in BINANCE_SYMBOLS:
        t = ticker_map.get(symbol)
        if not t:
            continue

        try:
            price = float(t["lastPrice"])
            change_pct = float(t["priceChangePercent"])
            quote_volume = float(t["quoteVolume"])
            high = float(t["highPrice"])
            low = float(t["lowPrice"])
            weighted_avg = float(t["weightedAvgPrice"]) if float(t["weightedAvgPrice"]) else price

            range_pct = ((high - low) / price) * 100 if price else 0
            rvol = clamp(quote_volume / 1_000_000_000, 0.5, 3.0)
            above_vwap = price >= weighted_avg
            breakout = price >= high * 0.998 or price <= low * 1.002

            score, signal, direction = score_row(
                "Crypto", symbol, price, change_pct, rvol, range_pct, above_vwap, breakout, quote_volume / 1_000_000
            )

            rows.append({
                "asset": "Crypto",
                "symbol": symbol,
                "price": round(price, 4) if price < 100 else round(price, 2),
                "change_pct": round(change_pct, 2),
                "rvol": round(rvol, 2),
                "range_pct": round(range_pct, 2),
                "score": score,
                "signal": signal,
                "bias": direction,
                "updated": datetime.now().strftime("%H:%M:%S"),
            })

        except Exception as e:
            log_error(f"Crypto {symbol}: {e}")

    return rows
def scan_polygon_stocks():
    rows = []
    if not (POLYGON_API_KEY and POLYGON_STOCKS):
        return rows

    for symbol in POLYGON_STOCKS:
        try:
            snap = safe_get_json(f"https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers/{symbol}?apiKey={POLYGON_API_KEY}")
            ticker = snap.get("ticker", {})
            day = ticker.get("day", {})
            prev = ticker.get("prevDay", {})
            minv = ticker.get("min", {})

            price = float(ticker.get("lastTrade", {}).get("p") or minv.get("c") or day.get("c") or 0)
            prev_close = float(prev.get("c") or 0)
            if not price or not prev_close:
                continue

            change_pct = ((price - prev_close) / prev_close) * 100
            volume = float(day.get("v") or 0)
            avg_size = max(float(prev.get("v") or 1), 1)
            rvol = clamp(volume / avg_size, 0.5, 3.0)

            high = float(day.get("h") or price)
            low = float(day.get("l") or price)
            vwap = float(day.get("vw") or price)
            range_pct = ((high - low) / price) * 100 if price else 0
            above_vwap = price >= vwap
            breakout = price >= high * 0.998 or price <= low * 1.002
            dollar_vol_m = (volume * price) / 1_000_000

            score, signal, direction = score_row(
                "Stock", symbol, price, change_pct, rvol, range_pct, above_vwap, breakout, dollar_vol_m
            )

            rows.append({
                "asset": "Stock",
                "symbol": symbol,
                "price": round(price, 2),
                "change_pct": round(change_pct, 2),
                "rvol": round(rvol, 2),
                "range_pct": round(range_pct, 2),
                "score": score,
                "signal": signal,
                "bias": direction,
                "updated": datetime.now().strftime("%H:%M:%S"),
            })
        except Exception as e:
            log_error(f"Stock {symbol}: {e}")
    return rows

def scan_polygon_forex():
    rows = []
    if not (POLYGON_API_KEY and POLYGON_FOREX):
        return rows

    for symbol in POLYGON_FOREX:
        try:
            snap = safe_get_json(f"https://api.polygon.io/v2/snapshot/locale/global/markets/forex/tickers/{symbol}?apiKey={POLYGON_API_KEY}")
            ticker = snap.get("ticker", {})
            day = ticker.get("day", {})
            prev = ticker.get("prevDay", {})
            lastq = ticker.get("lastQuote", {})

            price = float(lastq.get("a") or day.get("c") or 0)
            prev_close = float(prev.get("c") or 0)
            if not price or not prev_close:
                continue

            change_pct = ((price - prev_close) / prev_close) * 100
            high = float(day.get("h") or price)
            low = float(day.get("l") or price)
            vwap = float(day.get("vw") or price)
            range_pct = ((high - low) / price) * 100 if price else 0
            above_vwap = price >= vwap
            breakout = price >= high * 0.998 or price <= low * 1.002
            # Forex snapshots do not provide strong volume equivalents here, so keep neutral participation.
            rvol = 1.1
            dollar_vol_m = 60

            score, signal, direction = score_row(
                "Forex", symbol, price, change_pct, rvol, range_pct, above_vwap, breakout, dollar_vol_m
            )

            rows.append({
                "asset": "Forex",
                "symbol": symbol.replace("C:", ""),
                "price": round(price, 5),
                "change_pct": round(change_pct, 2),
                "rvol": round(rvol, 2),
                "range_pct": round(range_pct, 2),
                "score": score,
                "signal": signal,
                "bias": direction,
                "updated": datetime.now().strftime("%H:%M:%S"),
            })
        except Exception as e:
            log_error(f"Forex {symbol}: {e}")
    return rows

def scanner_loop():
    while True:
        try:
            rows = []
            rows.extend(scan_binance())
            rows.extend(scan_polygon_stocks())
            rows.extend(scan_polygon_forex())

            rows = sorted(rows, key=lambda x: x["score"], reverse=True)

            for row in rows:
                update_score(row["symbol"], row["score"])
                if should_alert(row["symbol"], row["score"], row["signal"]):
                    msg = (
                        f"{row['signal']} alert\n"
                        f"{row['symbol']} ({row['asset']})\n"
                        f"Score: {row['score']}\n"
                        f"Price: {row['price']}\n"
                        f"Change: {row['change_pct']}%\n"
                        f"Bias: {row['bias']}"
                    )
                    ok, detail = send_sms(msg)
                    if ok:
                        mark_alert(row["symbol"], row["score"])
                    else:
                        log_error(f"SMS {row['symbol']}: {detail}")

            with state_lock:
                state["rows"] = rows
                state["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                state["status"] = "running"
        except Exception as e:
            log_error(f"scanner: {e}")
            with state_lock:
                state["status"] = "error"

        time.sleep(POLL_SECONDS)

def ensure_thread():
    with state_lock:
        if state["thread_started"]:
            return
        state["thread_started"] = True

    t = threading.Thread(target=scanner_loop, daemon=True)
    t.start()

ensure_thread()

st.title("Trading Dashboard")
st.caption("Balanced live scanner: moderate alert flow, cross-asset ranking, SMS on stronger setups")

c1, c2, c3, c4 = st.columns(4)
with state_lock:
    rows = list(state["rows"])
    last_update = state["last_update"]
    status = state["status"]
    errors = list(state["errors"])

df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["asset", "symbol", "price", "change_pct", "rvol", "range_pct", "score", "signal", "bias", "updated"])

c1.metric("Scanner Status", status.title())
c2.metric("Last Update", last_update or "Waiting")
c3.metric("Alert Threshold", f"{ALERT_THRESHOLD:.0f}")
c4.metric("Poll Interval", f"{POLL_SECONDS}s")

st.markdown("### Filters")
f1, f2, f3 = st.columns(3)
asset_filter = f1.multiselect("Asset classes", ["Crypto", "Stock", "Forex"], default=["Crypto", "Stock", "Forex"])
min_score = f2.slider("Minimum score", 0, 100, 60)
signals = f3.multiselect("Signals", ["Watch", "Breakout", "Momentum", "A+"], default=["Breakout", "Momentum", "A+"])

if not df.empty:
    filtered = df[df["asset"].isin(asset_filter) & (df["score"] >= min_score) & (df["signal"].isin(signals))]
else:
    filtered = df

st.markdown("### Ranked opportunities")
st.dataframe(filtered, use_container_width=True, hide_index=True)

st.markdown("### Notes")
st.write("- Balanced mode aims for a threshold around 70 with moderate alert frequency.")
st.write("- Crypto uses Binance public market data.")
st.write("- Stocks and forex use Polygon snapshots when POLYGON_API_KEY is set.")
st.write("- SMS alerts only fire on stronger setups and use cooldown logic to reduce spam.")

if errors:
    st.markdown("### Recent errors")
    for e in errors[:8]:
        st.code(e)

st.markdown("### Required environment variables")
st.code(
    "TWILIO_ACCOUNT_SID\nTWILIO_AUTH_TOKEN\nTWILIO_FROM\nTWILIO_TO\nPOLYGON_API_KEY\n"
    "BINANCE_SYMBOLS\nPOLYGON_STOCKS\nPOLYGON_FOREX\nPOLL_SECONDS\nALERT_THRESHOLD\nALERT_COOLDOWN_MINUTES"
)
