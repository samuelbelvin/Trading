import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf

st.set_page_config(page_title="Most Likely Profitable Pairs Dashboard", layout="wide")

DEFAULT_FOREX = "EURUSD=X,GBPUSD=X,USDJPY=X,AUDUSD=X,USDCAD=X"
DEFAULT_CRYPTO = "BTC-USD,ETH-USD,SOL-USD,XRP-USD,ADA-USD"

FOREX_SYMBOLS = [s.strip().upper() for s in os.getenv("FOREX_SYMBOLS", DEFAULT_FOREX).split(",") if s.strip()]
CRYPTO_SYMBOLS = [s.strip().upper() for s in os.getenv("CRYPTO_SYMBOLS", DEFAULT_CRYPTO).split(",") if s.strip()]
LOOKBACK_PERIOD = os.getenv("LOOKBACK_PERIOD", "5d")
INTERVAL = os.getenv("INTERVAL", "15m")
AUTO_REFRESH_SECONDS = max(60, int(os.getenv("AUTO_REFRESH_SECONDS", "300")))


def clamp(val: float, low: float, high: float) -> float:
    return max(low, min(high, val))


def rsi(series: pd.Series, period: int = 14) -> float:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi_series = 100 - (100 / (1 + rs))
    value = rsi_series.iloc[-1]
    return float(value) if pd.notna(value) else 50.0


def normalize_symbol(symbol: str) -> str:
    if symbol.endswith("=X"):
        return symbol.replace("=X", "")
    return symbol


def fetch_symbol_frame(symbol: str, period: str, interval: str) -> pd.DataFrame:
    df = yf.download(
        tickers=symbol,
        period=period,
        interval=interval,
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    if df is None or df.empty:
        return pd.DataFrame()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]

    cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
    if not cols:
        return pd.DataFrame()

    df = df[cols].dropna().copy()
    return df


def score_pair(asset_class: str, symbol: str, df: pd.DataFrame):
    if df.empty or len(df) < 30:
        return None

    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    volume = df["Volume"].astype(float) if "Volume" in df.columns else pd.Series(index=df.index, dtype=float)

    last_price = float(close.iloc[-1])

    ret_short = ((close.iloc[-1] / close.iloc[-5]) - 1) * 100 if len(close) >= 5 else 0.0
    ret_4h = ((close.iloc[-1] / close.iloc[-17]) - 1) * 100 if len(close) >= 17 else ret_short
    ret_day = ((close.iloc[-1] / close.iloc[0]) - 1) * 100

    ema_9 = close.ewm(span=9).mean().iloc[-1]
    ema_21 = close.ewm(span=21).mean().iloc[-1]

    true_range = pd.concat(
        [
            (high - low),
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr_pct = float((true_range.rolling(14).mean().iloc[-1] / last_price) * 100) if last_price else 0.0

    breakout_window = 20
    recent_high = float(high.tail(breakout_window).max())
    recent_low = float(low.tail(breakout_window).min())

    breakout_up = last_price >= recent_high * 0.998
    breakout_down = last_price <= recent_low * 1.002

    if ema_9 > ema_21 and last_price > ema_9:
        momentum_bias = "Bullish"
    elif ema_9 < ema_21 and last_price < ema_9:
        momentum_bias = "Bearish"
    else:
        momentum_bias = "Mixed"

    current_rsi = rsi(close, 14)

    if momentum_bias == "Bullish":
        rsi_score = clamp(70 - abs(62 - current_rsi), 0, 12)
    elif momentum_bias == "Bearish":
        rsi_score = clamp(70 - abs(38 - current_rsi), 0, 12)
    else:
        rsi_score = clamp(30 - abs(50 - current_rsi), 0, 8)

    volatility_score = clamp(atr_pct * 7, 0, 20)
    trend_score = clamp(abs(ret_4h) * 2.5, 0, 20)
    day_score = clamp(abs(ret_day) * 1.2, 0, 15)
    breakout_score = 15 if (breakout_up or breakout_down) else 0
    alignment_score = 12 if (
        (ema_9 > ema_21 and ret_short > 0 and ret_4h > 0)
        or (ema_9 < ema_21 and ret_short < 0 and ret_4h < 0)
    ) else 0

    volume_score = 0.0
    volume_ratio = np.nan
    if asset_class == "Crypto" and "Volume" in df.columns and volume.notna().any():
        vol_ma = volume.rolling(20).mean().iloc[-1]
        if pd.notna(vol_ma) and vol_ma > 0:
            volume_ratio = float(volume.iloc[-1] / vol_ma)
            volume_score = clamp(volume_ratio * 6, 0, 18)

    raw_score = (
        trend_score
        + day_score
        + volatility_score
        + breakout_score
        + alignment_score
        + rsi_score
        + volume_score
    )
    score = round(clamp(raw_score, 0, 100), 2)

    setup = "Watch"
    if score >= 80:
        setup = "High Conviction"
    elif score >= 68:
        setup = "Strong"
    elif score >= 55:
        setup = "Developing"

    if momentum_bias == "Bullish":
        direction = "Long"
    elif momentum_bias == "Bearish":
        direction = "Short"
    else:
        direction = "Neutral"

    return {
        "asset_class": asset_class,
        "pair": normalize_symbol(symbol),
        "price": round(last_price, 5 if asset_class == "Forex" else 2),
        "score": score,
        "setup": setup,
        "direction": direction,
        "bias": momentum_bias,
        "rsi": round(float(current_rsi), 2),
        "atr_pct": round(float(atr_pct), 2),
        "ret_short_pct": round(float(ret_short), 2),
        "ret_4h_pct": round(float(ret_4h), 2),
        "ret_day_pct": round(float(ret_day), 2),
        "breakout": "Up" if breakout_up else "Down" if breakout_down else "No",
        "ema9_vs_ema21": "Above" if ema_9 > ema_21 else "Below",
        "volume_ratio": round(float(volume_ratio), 2) if pd.notna(volume_ratio) else None,
        "updated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    }


@st.cache_data(ttl=AUTO_REFRESH_SECONDS, show_spinner=False)
def build_rankings(forex_symbols: tuple[str, ...], crypto_symbols: tuple[str, ...], period: str, interval: str):
    rows = []
    errors = []

    for symbol in forex_symbols:
        try:
            frame = fetch_symbol_frame(symbol, period, interval)
            row = score_pair("Forex", symbol, frame)
            if row:
                rows.append(row)
            else:
                errors.append(f"Not enough data for forex pair {symbol}")
        except Exception as exc:
            errors.append(f"Forex {symbol}: {exc}")

    for symbol in crypto_symbols:
        try:
            frame = fetch_symbol_frame(symbol, period, interval)
            row = score_pair("Crypto", symbol, frame)
            if row:
                rows.append(row)
            else:
                errors.append(f"Not enough data for crypto pair {symbol}")
        except Exception as exc:
            errors.append(f"Crypto {symbol}: {exc}")

    rows = sorted(rows, key=lambda x: x["score"], reverse=True)
    return rows, errors


st.title("Most Likely Profitable Pairs Dashboard")
st.caption("Ranks forex and crypto pairs by trend, breakout pressure, volatility, and momentum alignment.")

top_left, top_right = st.columns([1, 3])
with top_left:
    if st.button("Refresh now", use_container_width=True):
        build_rankings.clear()
        st.rerun()
with top_right:
    st.write(f"Auto-refresh cache TTL: {AUTO_REFRESH_SECONDS}s | Period: {LOOKBACK_PERIOD} | Interval: {INTERVAL}")

rows, errors = build_rankings(tuple(FOREX_SYMBOLS), tuple(CRYPTO_SYMBOLS), LOOKBACK_PERIOD, INTERVAL)

df = pd.DataFrame(rows)
if df.empty:
    df = pd.DataFrame(
        columns=[
            "asset_class",
            "pair",
            "price",
            "score",
            "setup",
            "direction",
            "bias",
            "rsi",
            "atr_pct",
            "ret_short_pct",
            "ret_4h_pct",
            "ret_day_pct",
            "breakout",
            "ema9_vs_ema21",
            "volume_ratio",
            "updated_utc",
        ]
    )

c1, c2, c3, c4 = st.columns(4)
c1.metric("Pairs ranked", len(df))
c2.metric("Top score", f"{df['score'].max():.2f}" if not df.empty else "0")
c3.metric("Top forex", df[df["asset_class"] == "Forex"].iloc[0]["pair"] if not df[df["asset_class"] == "Forex"].empty else "None")
c4.metric("Top crypto", df[df["asset_class"] == "Crypto"].iloc[0]["pair"] if not df[df["asset_class"] == "Crypto"].empty else "None")

st.markdown("### Filters")
f1, f2, f3 = st.columns(3)
asset_filter = f1.multiselect("Asset classes", ["Forex", "Crypto"], default=["Forex", "Crypto"])
min_score = f2.slider("Minimum score", 0, 100, 55)
setup_filter = f3.multiselect(
    "Setup strength",
    ["Developing", "Strong", "High Conviction"],
    default=["Developing", "Strong", "High Conviction"],
)

filtered = df[
    df["asset_class"].isin(asset_filter)
    & (df["score"] >= min_score)
    & (df["setup"].isin(setup_filter))
]

st.markdown("### Ranked opportunities")
st.dataframe(filtered, use_container_width=True, hide_index=True)

st.markdown("### Top 5 overall")
top5 = df.head(5)[["asset_class", "pair", "score", "setup", "direction", "ret_4h_pct", "atr_pct", "breakout"]]
st.dataframe(top5, use_container_width=True, hide_index=True)

if errors:
    st.markdown("### Diagnostics")
    for err in errors[:12]:
        st.code(err)

st.markdown("### Model notes")
st.write("- Forex symbols must use Yahoo Finance format like EURUSD=X.")
st.write("- Crypto symbols must use Yahoo Finance format like BTC-USD.")
st.write("- Score emphasizes trend alignment, breakout proximity, volatility, and crypto volume confirmation.")
st.write("- This is a ranking dashboard, not an execution engine.")
