import os
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests
import streamlit as st
from streamlit_autorefresh import st_autorefresh

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
    for s in os.getenv("POLYGON_FOREX", "").split(",")
    if s.strip()
]

POLL_SECONDS = int(os.getenv("POLL_SECONDS", "15"))
ALERT_THRESHOLD = float(os.getenv("ALERT_THRESHOLD", "70"))
ALERT_COOLDOWN_MINUTES = int(os.getenv("ALERT_COOLDOWN_MINUTES", "20"))

st_autorefresh(interval=POLL_SECONDS * 1000, key="dashboard_refresh")

if "rows" not in st.session_state:
    st.session_state.rows = []
if "last_update" not in st.session_state:
    st.session_state.last_update = None
if "status" not in st.session_state:
    st.session_state.status = "starting"
if "errors" not in st.session_state:
    st.session_state.errors = []
if "last_alerts" not in st.session_state:
    st.session_state.last_alerts = {}
if "last_scores" not in st.session_state:
    st.session_state.last_scores = {}


def log_error(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    st.session_state.errors = [f"{ts} - {msg}"] + st.session_state.errors[:9]


def safe_get_json(url: str, timeout: int = 12):
    try:
        response = requests.get(url, timeout=timeout)
        if response.status_code != 200:
            raise Exception(f"{response.status_code} error")
        return response.json()
    except Exception as e:
        log_error(f"Request failed: {url} | {e}")
        return None


twilio_client = None
if Client and all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM, TWILIO_TO]):
    try:
        twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    except Exception as e:
        log_error(f"Twilio init failed: {e}")


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


def score_row(price, change_pct, rvol, range_pct, above_vwap, breakout, dollar_vol_m):
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

    bias = "Bullish" if change_pct >= 0 else "Bearish"
    return round(score, 2), signal, bias


def should_alert(symbol, score, signal):
    now = datetime.now(timezone.utc)
    prev_score = st.session_state.last_scores.get(symbol, 0)
    last_alert_iso = st.session_state.last_alerts.get(symbol)

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
    st.session_state.last_alerts[symbol] = datetime.now(timezone.utc).isoformat()
    st.session_state.last_scores[symbol] = score


def update_score(symbol, score):
    st.session_state.last_scores[symbol] = score


def scan_polygon_stocks():
    rows = []
    if not (POLYGON_API_KEY and POLYGON_STOCKS):
        return rows

    for symbol in POLYGON_STOCKS:
        try:
            url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/prev?adjusted=true&apiKey={POLYGON_API_KEY}"
            data = safe_get_json(url)
            if not data:
                log_error(f"{symbol}: no response")
                continue
            if "results" not in data or not data["results"]:
                log_error(f"{symbol}: no results returned")
                continue

            r = data["results"][0]
            price = float(r.get("c") or 0)
            open_price = float(r.get("o") or 0)
            high = float(r.get("h") or 0)
            low = float(r.get("l") or 0)
            volume = float(r.get("v") or 0)
            vwap = float(r.get("vw") or open_price or price or 0)

            if not price or not open_price:
                log_error(f"{symbol}: missing price/open")
                continue

            change_pct = ((price - open_price) / open_price) * 100
            range_pct = ((high - low) / price) * 100 if price else 0
            rvol = 1.2
            above_vwap = price >= vwap
            breakout = price >= high * 0.998 or price <= low * 1.002
            dollar_vol_m = (volume * price) / 1_000_000

            score, signal, bias = score_row(
                price, change_pct, rvol, range_pct, above_vwap, breakout, dollar_vol_m
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
                "bias": bias,
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
            url = f"https://api.polygon.io/v2/snapshot/locale/global/markets/forex/tickers/{symbol}?apiKey={POLYGON_API_KEY}"
            data = safe_get_json(url)
            if not data:
                log_error(f"{symbol}: no response")
                continue

            ticker = data.get("ticker", {})
            day = ticker.get("day", {})
            last_quote = ticker.get("lastQuote", {})
            prev_day = ticker.get("prevDay", {})

            ask = last_quote.get("a")
            close = day.get("c")
            prev_close = prev_day.get("c")
            high = day.get("h")
            low = day.get("l")

            price = float(ask or close or 0)
            prev_close = float(prev_close or 0)
            high = float(high or price or 0)
            low = float(low or price or 0)

            if not price or not prev_close:
                log_error(f"{symbol}: missing forex price")
                continue

            change_pct = ((price - prev_close) / prev_close) * 100
            range_pct = ((high - low) / price) * 100 if price else 0
            rvol = 1.0
            above_vwap = price >= prev_close
            breakout = price >= high * 0.998 or price <= low * 1.002
            dollar_vol_m = 10

            score, signal, bias = score_row(
                price, change_pct, rvol, range_pct, above_vwap, breakout, dollar_vol_m
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
                "bias": bias,
                "updated": datetime.now().strftime("%H:%M:%S"),
            })
        except Exception as e:
            log_error(f"Forex {symbol}: {e}")

    return rows


def run_scan():
    try:
        rows = []
        rows.extend(scan_polygon_stocks())
        rows.extend(scan_polygon_forex())
        rows = sorted(rows, key=lambda x: x["score"], reverse=True)

        for row in rows:
            if should_alert(row["symbol"], row["score"], row["signal"]):
                msg = (
                    f"{row['signal']} alert\\n"
                    f"{row['symbol']} ({row['asset']})\\n"
                    f"Score: {row['score']}\\n"
                    f"Price: {row['price']}\\n"
                    f"Change: {row['change_pct']}%\\n"
                    f"Bias: {row['bias']}"
                )
                ok, detail = send_sms(msg)
                if ok:
                    mark_alert(row["symbol"], row["score"])
                else:
                    log_error(f"SMS {row['symbol']}: {detail}")

            update_score(row["symbol"], row["score"])

        st.session_state.rows = rows
        st.session_state.last_update = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        st.session_state.status = "running"
    except Exception as e:
        log_error(f"scanner: {e}")
        st.session_state.status = "error"


run_scan()

st.title("Trading Dashboard")
st.caption("Balanced live scanner: Streamlit-safe refresh model, stocks + forex ranking, SMS on stronger setups")

c1, c2, c3, c4 = st.columns(4)
rows = list(st.session_state.rows)
last_update = st.session_state.last_update
status = st.session_state.status
errors = list(st.session_state.errors)

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
asset_choices = ["Stock"] + (["Forex"] if POLYGON_FOREX else [])
asset_filter = f1.multiselect("Asset classes", asset_choices, default=asset_choices)
min_score = f2.slider("Minimum score", 0, 100, 0)
signals = f3.multiselect(
    "Signals",
    ["Watch", "Breakout", "Momentum", "A+"],
    default=["Watch", "Breakout", "Momentum", "A+"]
)

if not df.empty:
    filtered = df[
        df["asset"].isin(asset_filter)
        & (df["score"] >= min_score)
        & (df["signal"].isin(signals))
    ]
else:
    filtered = df

st.markdown("### Ranked opportunities")
st.dataframe(filtered, width="stretch", hide_index=True)

st.markdown("### Notes")
st.write("- This version uses Streamlit-safe reruns instead of a blocking infinite loop.")
st.write("- Stock data uses Polygon previous-day aggregates.")
st.write("- Forex uses Polygon snapshot data when POLYGON_FOREX is set.")
st.write("- Filters default to show all rows, including Watch.")

missing = []
if not POLYGON_API_KEY:
    missing.append("POLYGON_API_KEY")
if not POLYGON_STOCKS:
    missing.append("POLYGON_STOCKS")
if missing:
    st.error("Missing required configuration: " + ", ".join(missing))

if errors:
    st.markdown("### Recent errors")
    for e in errors[:8]:
        st.code(e)

st.markdown("### Required environment variables")
st.code(
    "TWILIO_ACCOUNT_SID\\n"
    "TWILIO_AUTH_TOKEN\\n"
    "TWILIO_FROM\\n"
    "TWILIO_TO\\n"
    "POLYGON_API_KEY\\n"
    "POLYGON_STOCKS\\n"
    "POLYGON_FOREX\\n"
    "POLL_SECONDS\\n"
    "ALERT_THRESHOLD\\n"
    "ALERT_COOLDOWN_MINUTES"
)
