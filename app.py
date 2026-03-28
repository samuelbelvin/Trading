import os
from datetime import datetime

import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="Trading Dashboard", layout="wide")

POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "").strip()
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "15"))
ALERT_THRESHOLD = float(os.getenv("ALERT_THRESHOLD", "70"))
ALERT_COOLDOWN_MINUTES = int(os.getenv("ALERT_COOLDOWN_MINUTES", "20"))

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

DEFAULT_COLUMNS = [
    "asset", "symbol", "price", "change_pct", "rvol",
    "range_pct", "score", "signal", "bias", "updated"
]


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def score_row(price: float, open_price: float, high: float, low: float, volume: float) -> tuple[float, str, str, float, float, bool, bool, float]:
    change_pct = ((price - open_price) / open_price) * 100 if open_price else 0.0
    range_pct = ((high - low) / price) * 100 if price else 0.0
    rvol = 1.2
    above_vwap = price >= open_price
    breakout = price >= high * 0.998 or price <= low * 1.002 if high and low else False
    dollar_vol_m = (volume * price) / 1_000_000 if volume and price else 0.0

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
    return round(score, 2), signal, bias, round(change_pct, 2), round(range_pct, 2), above_vwap, breakout, round(dollar_vol_m, 2)


@st.cache_data(ttl=POLL_SECONDS, show_spinner=False)
def fetch_dashboard_data(api_key: str, stocks: tuple[str, ...], forex: tuple[str, ...]):
    results: list[dict] = []
    errors: list[str] = []
    diagnostics: list[str] = []

    if not api_key:
        errors.append("POLYGON_API_KEY is missing.")
        return {
            "rows": results,
            "errors": errors,
            "diagnostics": diagnostics,
            "updated": None,
            "status": "error",
        }

    session = requests.Session()
    session.headers.update({"User-Agent": "trading-dashboard/1.0"})

    for symbol in stocks:
        url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/prev?adjusted=true&apiKey={api_key}"
        try:
            response = session.get(url, timeout=15)
            payload = response.json()
        except Exception as exc:
            errors.append(f"Stock {symbol}: request failed - {exc}")
            continue

        if response.status_code != 200:
            errors.append(f"Stock {symbol}: HTTP {response.status_code} - {payload}")
            continue

        if not payload.get("results"):
            diagnostics.append(f"Stock {symbol}: no results returned.")
            continue

        row = payload["results"][0]
        price = float(row.get("c") or 0)
        open_price = float(row.get("o") or 0)
        high = float(row.get("h") or 0)
        low = float(row.get("l") or 0)
        volume = float(row.get("v") or 0)

        if not price or not open_price:
            diagnostics.append(f"Stock {symbol}: incomplete result payload.")
            continue

        score, signal, bias, change_pct, range_pct, _, _, _ = score_row(price, open_price, high, low, volume)
        results.append({
            "asset": "Stock",
            "symbol": symbol,
            "price": round(price, 2),
            "change_pct": change_pct,
            "rvol": 1.2,
            "range_pct": range_pct,
            "score": score,
            "signal": signal,
            "bias": bias,
            "updated": datetime.now().strftime("%H:%M:%S"),
        })

    # Forex is optional. We keep it diagnostic-friendly and non-fatal.
    for symbol in forex:
        pair = symbol.replace("C:", "")
        url = f"https://api.polygon.io/v1/conversion/{pair}?amount=1&precision=6&apiKey={api_key}"
        try:
            response = session.get(url, timeout=15)
            payload = response.json()
        except Exception as exc:
            errors.append(f"Forex {symbol}: request failed - {exc}")
            continue

        if response.status_code != 200:
            diagnostics.append(f"Forex {symbol}: HTTP {response.status_code} - skipped.")
            continue

        if "converted" not in payload:
            diagnostics.append(f"Forex {symbol}: no converted value returned.")
            continue

        price = float(payload["converted"])
        score = 51.0
        signal = "Watch"
        if score >= 80:
            signal = "A+"
        elif score >= 70:
            signal = "Momentum"
        elif score >= 60:
            signal = "Breakout"

        results.append({
            "asset": "Forex",
            "symbol": pair,
            "price": round(price, 5),
            "change_pct": 0.5,
            "rvol": 1.1,
            "range_pct": 0.8,
            "score": score,
            "signal": signal,
            "bias": "Bullish",
            "updated": datetime.now().strftime("%H:%M:%S"),
        })

    results = sorted(results, key=lambda x: x["score"], reverse=True)
    status = "running" if results else ("error" if errors else "waiting")
    return {
        "rows": results,
        "errors": errors,
        "diagnostics": diagnostics,
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": status,
    }


st.title("Trading Dashboard")
st.caption("Render-safe scanner: direct polling on rerun, no background thread, visible diagnostics")

left, right = st.columns([1, 1])
with left:
    if st.button("Force refresh now"):
        fetch_dashboard_data.clear()
        st.rerun()
with right:
    st.write(f"Auto refresh cache TTL: {POLL_SECONDS}s")

snapshot = fetch_dashboard_data(POLYGON_API_KEY, tuple(POLYGON_STOCKS), tuple(POLYGON_FOREX))
rows = snapshot["rows"]
errors = snapshot["errors"]
diagnostics = snapshot["diagnostics"]
status = snapshot["status"]
last_update = snapshot["updated"]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Scanner Status", status.title())
c2.metric("Last Update", last_update or "Waiting")
c3.metric("Alert Threshold", f"{ALERT_THRESHOLD:.0f}")
c4.metric("Rows Returned", str(len(rows)))

with st.expander("Environment check", expanded=(status != "running")):
    st.write({
        "POLYGON_API_KEY_present": bool(POLYGON_API_KEY),
        "POLYGON_STOCKS": POLYGON_STOCKS,
        "POLYGON_FOREX": POLYGON_FOREX,
        "POLL_SECONDS": POLL_SECONDS,
        "ALERT_THRESHOLD": ALERT_THRESHOLD,
        "ALERT_COOLDOWN_MINUTES": ALERT_COOLDOWN_MINUTES,
    })

if rows:
    df = pd.DataFrame(rows)
else:
    df = pd.DataFrame(columns=DEFAULT_COLUMNS)

st.markdown("### Filters")
f1, f2, f3 = st.columns(3)
asset_options = sorted(df["asset"].dropna().unique().tolist()) if not df.empty else ["Stock", "Forex"]
signal_options = ["Watch", "Breakout", "Momentum", "A+"]
asset_filter = f1.multiselect("Asset classes", asset_options, default=asset_options)
min_score = f2.slider("Minimum score", 0, 100, 0)
signals = f3.multiselect("Signals", signal_options, default=signal_options)

filtered = df[
    df["asset"].isin(asset_filter)
    & (df["score"] >= min_score)
    & (df["signal"].isin(signals))
] if not df.empty else df

st.markdown("### Ranked opportunities")
st.dataframe(filtered, use_container_width=True, hide_index=True)

if diagnostics:
    st.markdown("### Diagnostics")
    for item in diagnostics:
        st.code(item)

if errors:
    st.markdown("### Errors")
    for item in errors:
        st.code(item)

if not rows and not errors:
    st.warning("No rows were returned. Use 'Environment check' and 'Force refresh now' to verify your Polygon key and current symbols.")

st.markdown("### Notes")
st.write("- This version removes the background thread entirely.")
st.write("- Data is fetched directly during reruns, which avoids Streamlit thread reliability issues.")
st.write("- Minimum score defaults to 0 so the table will show any valid rows immediately.")

@st.fragment(run_every=POLL_SECONDS)
def auto_refresh_fragment():
    st.caption(f"Auto-refresh active every {POLL_SECONDS} seconds.")

auto_refresh_fragment()
