
import os
from datetime import datetime, timezone

import requests
import streamlit as st

st.set_page_config(page_title="Real Data Forex + Crypto Pairs Dashboard", layout="wide")

OANDA_API_KEY = os.getenv("OANDA_API_KEY", "").strip()
OANDA_ACCOUNT_ID = os.getenv("OANDA_ACCOUNT_ID", "").strip()
OANDA_ENV = os.getenv("OANDA_ENV", "practice").strip().lower()

FOREX_SYMBOLS = [s.strip().upper() for s in os.getenv("FOREX_SYMBOLS", "EUR_USD,GBP_USD,USD_JPY,AUD_USD,USD_CAD").split(",") if s.strip()]
CRYPTO_SYMBOLS = [s.strip().upper() for s in os.getenv("CRYPTO_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,ADAUSDT").split(",") if s.strip()]

FOREX_GRANULARITY = os.getenv("FOREX_GRANULARITY", "M15").strip()
CRYPTO_INTERVAL = os.getenv("CRYPTO_INTERVAL", "15m").strip()
CANDLE_COUNT = max(60, int(os.getenv("CANDLE_COUNT", "120")))
AUTO_REFRESH_SECONDS = max(30, int(os.getenv("AUTO_REFRESH_SECONDS", "60")))

OANDA_BASE_URL = "https://api-fxtrade.oanda.com" if OANDA_ENV == "live" else "https://api-fxpractice.oanda.com"
BINANCE_BASE_URL = os.getenv("BINANCE_BASE_URL", "https://data-api.binance.vision").strip().rstrip("/")

def clamp(value, low, high):
    return max(low, min(high, value))

def mean(values):
    return sum(values) / len(values) if values else 0.0

def ema(values, span):
    if not values:
        return 0.0
    alpha = 2 / (span + 1)
    out = values[0]
    for v in values[1:]:
        out = alpha * v + (1 - alpha) * out
    return out

def compute_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    gains = []
    losses = []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0))
        losses.append(max(-delta, 0))
    avg_gain = mean(gains[-period:])
    avg_loss = mean(losses[-period:])
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def true_ranges(candles):
    trs = []
    prev_close = None
    for c in candles:
        high = c["high"]
        low = c["low"]
        if prev_close is None:
            tr = high - low
        else:
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
        prev_close = c["close"]
    return trs

def format_pair(pair):
    if pair.endswith("USDT"):
        return pair[:-4] + "/USDT"
    return pair.replace("_", "/")

def fetch_oanda_candles(instrument, granularity, count):
    if not OANDA_API_KEY:
        raise RuntimeError("Missing OANDA_API_KEY")
    headers = {"Authorization": f"Bearer {OANDA_API_KEY}"}
    url = f"{OANDA_BASE_URL}/v3/instruments/{instrument}/candles"
    params = {"price": "M", "granularity": granularity, "count": count}
    r = requests.get(url, headers=headers, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    candles = []
    for c in data.get("candles", []):
        if not c.get("complete"):
            continue
        mid = c.get("mid") or {}
        candles.append({
            "time": c.get("time"),
            "open": float(mid.get("o", 0)),
            "high": float(mid.get("h", 0)),
            "low": float(mid.get("l", 0)),
            "close": float(mid.get("c", 0)),
            "volume": None,
        })
    return candles

def fetch_binance_klines(symbol, interval, limit_count):
    url = f"{BINANCE_BASE_URL}/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit_count}
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    candles = []
    for row in data:
        candles.append({
            "time": row[0],
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
        })
    return candles

def score_candles(asset_class, symbol, candles):
    if len(candles) < 40:
        return None

    closes = [c["close"] for c in candles]
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    volumes = [c["volume"] for c in candles if c["volume"] is not None]

    last_price = closes[-1]
    ema9 = ema(closes[-30:], 9)
    ema21 = ema(closes[-40:], 21)
    rsi = compute_rsi(closes, 14)

    ret_1h = ((closes[-1] / closes[-5]) - 1) * 100 if len(closes) >= 5 else 0.0
    ret_4h = ((closes[-1] / closes[-17]) - 1) * 100 if len(closes) >= 17 else ret_1h
    ret_day = ((closes[-1] / closes[0]) - 1) * 100

    atr_values = true_ranges(candles)
    atr = mean(atr_values[-14:]) if len(atr_values) >= 14 else mean(atr_values)
    atr_pct = (atr / last_price) * 100 if last_price else 0.0

    recent_high = max(highs[-20:])
    recent_low = min(lows[-20:])
    breakout_up = last_price >= recent_high * 0.998
    breakout_down = last_price <= recent_low * 1.002

    if ema9 > ema21 and last_price > ema9:
        bias = "Bullish"
    elif ema9 < ema21 and last_price < ema9:
        bias = "Bearish"
    else:
        bias = "Mixed"

    if bias == "Bullish":
        direction = "Long"
        rsi_score = clamp(70 - abs(62 - rsi), 0, 12)
    elif bias == "Bearish":
        direction = "Short"
        rsi_score = clamp(70 - abs(38 - rsi), 0, 12)
    else:
        direction = "Neutral"
        rsi_score = clamp(30 - abs(50 - rsi), 0, 8)

    trend_score = clamp(abs(ret_4h) * 2.5, 0, 20)
    day_score = clamp(abs(ret_day) * 1.2, 0, 15)
    volatility_score = clamp(atr_pct * 7, 0, 20)
    breakout_score = 15 if (breakout_up or breakout_down) else 0
    alignment_score = 12 if (
        (ema9 > ema21 and ret_1h > 0 and ret_4h > 0) or
        (ema9 < ema21 and ret_1h < 0 and ret_4h < 0)
    ) else 0

    volume_ratio = None
    volume_score = 0.0
    if asset_class == "Crypto" and volumes:
        vol_ma = mean(volumes[-20:]) if len(volumes) >= 20 else mean(volumes)
        if vol_ma > 0:
            volume_ratio = candles[-1]["volume"] / vol_ma
            volume_score = clamp(volume_ratio * 6, 0, 18)

    score = round(clamp(
        trend_score + day_score + volatility_score + breakout_score + alignment_score + rsi_score + volume_score,
        0,
        100,
    ), 2)

    setup = "Watch"
    if score >= 80:
        setup = "High Conviction"
    elif score >= 68:
        setup = "Strong"
    elif score >= 55:
        setup = "Developing"

    return {
        "asset_class": asset_class,
        "pair": format_pair(symbol),
        "price": round(last_price, 5 if asset_class == "Forex" else 4),
        "score": score,
        "setup": setup,
        "direction": direction,
        "bias": bias,
        "rsi": round(rsi, 2),
        "atr_pct": round(atr_pct, 2),
        "ret_1h_pct": round(ret_1h, 2),
        "ret_4h_pct": round(ret_4h, 2),
        "ret_day_pct": round(ret_day, 2),
        "breakout": "Up" if breakout_up else "Down" if breakout_down else "No",
        "ema9_vs_ema21": "Above" if ema9 > ema21 else "Below",
        "volume_ratio": round(volume_ratio, 2) if volume_ratio is not None else None,
        "updated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    }

@st.cache_data(ttl=AUTO_REFRESH_SECONDS, show_spinner=False)
def build_rankings():
    rows = []
    errors = []

    for symbol in FOREX_SYMBOLS:
        try:
            candles = fetch_oanda_candles(symbol, FOREX_GRANULARITY, CANDLE_COUNT)
            row = score_candles("Forex", symbol, candles)
            if row:
                rows.append(row)
            else:
                errors.append(f"Not enough usable OANDA candles for forex pair {symbol}")
        except Exception as exc:
            errors.append(f"Forex {symbol}: {exc}")

    for symbol in CRYPTO_SYMBOLS:
        try:
            candles = fetch_binance_klines(symbol, CRYPTO_INTERVAL, CANDLE_COUNT)
            row = score_candles("Crypto", symbol, candles)
            if row:
                rows.append(row)
            else:
                errors.append(f"Not enough usable Binance klines for crypto pair {symbol}")
        except Exception as exc:
            errors.append(f"Crypto {symbol}: {exc}")

    rows.sort(key=lambda x: x["score"], reverse=True)
    return rows, errors

st.title("Most Likely Profitable Pairs Dashboard")
st.caption("Real-data build: OANDA candles for forex, Binance market-data candles for crypto.")

left, right = st.columns([1, 3])
with left:
    if st.button("Refresh now", use_container_width=True):
        build_rankings.clear()
        st.rerun()
with right:
    st.write(
        f"Refresh cache: {AUTO_REFRESH_SECONDS}s | "
        f"Forex granularity: {FOREX_GRANULARITY} | Crypto interval: {CRYPTO_INTERVAL} | Candles: {CANDLE_COUNT}"
    )

rows, errors = build_rankings()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Pairs ranked", len(rows))
c2.metric("Top score", f"{rows[0]['score']:.2f}" if rows else "0")
c3.metric("Top forex", next((r["pair"] for r in rows if r["asset_class"] == "Forex"), "None"))
c4.metric("Top crypto", next((r["pair"] for r in rows if r["asset_class"] == "Crypto"), "None"))

st.markdown("### Filters")
f1, f2, f3 = st.columns(3)
asset_filter = f1.multiselect("Asset classes", ["Forex", "Crypto"], default=["Forex", "Crypto"])
min_score = f2.slider("Minimum score", 0, 100, 55)
setup_filter = f3.multiselect(
    "Setup strength",
    ["Developing", "Strong", "High Conviction"],
    default=["Developing", "Strong", "High Conviction"],
)

filtered = [
    r for r in rows
    if r["asset_class"] in asset_filter and r["score"] >= min_score and r["setup"] in setup_filter
]

st.markdown("### Ranked opportunities")
st.dataframe(filtered, use_container_width=True, hide_index=True)

st.markdown("### Top 5 overall")
st.dataframe(rows[:5], use_container_width=True, hide_index=True)

with st.expander("Data source status"):
    st.write(f"OANDA account id present: {bool(OANDA_ACCOUNT_ID)}")
    st.write(f"OANDA API key present: {bool(OANDA_API_KEY)}")
    st.write(f"OANDA environment: {OANDA_ENV}")
    st.write(f"Binance data endpoint: {BINANCE_BASE_URL}")

if errors:
    st.markdown("### Diagnostics")
    for err in errors[:20]:
        st.code(err)

st.markdown("### Model notes")
st.write("- Forex uses real OANDA candle data.")
st.write("- Crypto uses real Binance market-data klines.")
st.write("- Score emphasizes trend alignment, breakout pressure, volatility, and crypto volume confirmation.")
st.write("- This is a ranking dashboard, not an execution engine.")
