import os
import time
import threading
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests
import streamlit as st

try:
    from twilio.rest import Client
except Exception:
    Client = None


st.set_page_config(page_title="Trading Dashboard", layout="wide")

POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM = os.getenv("TWILIO_FROM", "")
TWILIO_TO = os.getenv("TWILIO_TO", "")

POLYGON_STOCKS = [
    s.strip().upper()
    for s in os.getenv("POLYGON_STOCKS", "AAPL,NVDA,TSLA,AMD,META,MSFT").split(",")
    if s.strip()
]
POLYGON_FOREX = [
    s.strip().upper()
    for s in os.getenv("POLYGON_FOREX", "C:EURUSD,C:GBPUSD,C:USDJPY").split(",")
    if s.strip()
]

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


def log_error(msg: str) -> None:
    with state_lock:
        state["errors"] = ([f"{datetime.now().strftime('%H:%M:%S')} - {msg}"] + state["errors"])[:10]


def safe_get_json(url: str, timeout: int = 12):
    try:
        response = requests.get(url, timeout=timeout)
        if response.status_code != 200:
            raise Exception(f"{response.status_code} error")
        return response.json()
    except Exception as e:
        log_error(f"Request failed: {url} | {e}")
        return None


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
    score = 0.0
    score += clamp(abs(change_pct) * 4, 0, 20)
    score += clamp(rvol * 12, 0, 24)
    score += clamp(range_pct * 3.5, 0, 18)
    score += clamp(dollar_vol_m / 50, 0, 18)
    score += 10 if above_vwap else 0
    score += 10 if breakout else 0

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


def scan_polygon_stocks():
    rows = []
    if not (POLYGON_API_KEY and POLYGON_STOCKS):
        return rows

    for symbol in POLYGON_STOCKS:
        try:
            url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/prev?adjusted=true&apiKey={POLYGON_API_KEY}"
            data = safe_get_json(url)
            if not data or "results" not in data or not data["results"]:
                continue

            r = data["results"][0]
            price = float(r.get("c") or 0)
            open_price = float(r.get("o") or 0)
            high = float(r.get("h") or 0)
            low = float(r.get("l") or 0)
            volume = float(r.get("v") or 0)

            if not price or not open_price:
                continue

            change_pct = ((price - open_price) / open_price) * 100
            range_pct = ((high - low) / price) * 100 if price else 0
            rvol = 1.2
            above_vwap = price >= open_price
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
            pair = symbol.replace("C:", "")
            url = f"https://api.polygon.io/v1/conversion/{pair}?amount=1&precision=6&apiKey={POLYGON_API_KEY}"
            data = safe_get_json(url)
            if not data or "converted" not in data:
                continue

            price = float(data["converted"])
            change_pct = 0.5
            range_pct = 0.8
            rvol = 1.1
            above_vwap = True
            breakout = False
            dollar_vol_m = 50

            score, signal, direction = score_row(
                "Forex", pair, price, change_pct, rvol, range_pct, above_vwap, breakout, dollar_vol_m
            )

            rows.append({
                "asset": "Forex",
                "symbol": pair,
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

            try:
                rows.extend(scan_polygon_stocks())
            except Exception as e:
                log_error(f"stocks loop: {e}")

            try:
                rows.extend(scan_polygon_forex())
            except Exception as e:
                log_error(f"forex loop: {e}")

            rows = sorted(rows, key=lambda x: x["score"], reverse=True)

            for row in rows:
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

                update_score(row["symbol"], row["score"])

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
st.caption("Balanced live scanner: moderate alert flow, stocks + forex ranking, SMS on stronger setups")

c1, c2, c3, c4 = st.columns(4)
with state_lock:
    rows = list(state["rows"])
    last_update = state["last_update"]
    status = state["status"]
    errors = list(state["errors"])

if rows:
    df = pd.DataFrame(rows)
else:
    df = pd.DataFrame(columns=[
        "asset", "symbol", "price", "change_pct", "rvol",
        "range_pct", "score", "signal", "bias", "updated"
    ])

c1.metric("Scanner Status", status.title())
c2.metric("Last Update", last_update or "Waiting")
c3.metric("Alert Threshold", f"{ALERT_THRESHOLD:.0f}")
c4.metric("Poll Interval", f"{POLL_SECONDS}s")

st.markdown("### Filters")
f1, f2, f3 = st.columns(3)
asset_filter = f1.multiselect("Asset classes", ["Stock", "Forex"], default=["Stock", "Forex"])
min_score = f2.slider("Minimum score", 0, 100, 60)
signals = f3.multiselect("Signals", ["Watch", "Breakout", "Momentum", "A+"], default=["Breakout", "Momentum", "A+"])

if not df.empty:
    filtered = df[
        df["asset"].isin(asset_filter)
        & (df["score"] >= min_score)
        & (df["signal"].isin(signals))
    ]
else:
    filtered = df

st.markdown("### Ranked opportunities")
st.dataframe(filtered, use_container_width=True, hide_index=True)

st.markdown("### Notes")
st.write("- Balanced mode aims for a threshold around 70 with moderate alert frequency.")
st.write("- Crypto is disabled in this version because Binance is blocked from the current server region.")
st.write("- Stocks use Polygon previous-day aggregates.")
st.write("- Forex uses Polygon conversion data.")
st.write("- SMS alerts only fire on stronger setups and use cooldown logic to reduce spam.")

if errors:
    st.markdown("### Recent errors")
    for e in errors[:8]:
        st.code(e)

st.markdown("### Required environment variables")
st.code(
    "TWILIO_ACCOUNT_SID\n"
    "TWILIO_AUTH_TOKEN\n"
    "TWILIO_FROM\n"
    "TWILIO_TO\n"
    "POLYGON_API_KEY\n"
    "POLYGON_STOCKS\n"
    "POLYGON_FOREX\n"
    "POLL_SECONDS\n"
    "ALERT_THRESHOLD\n"
    "ALERT_COOLDOWN_MINUTES"
)
