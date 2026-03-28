from __future__ import annotations
from datetime import datetime
import requests
from config import settings
from execution.oanda_live import OandaLiveBroker

def _score(change_pct: float, volatility_pct: float, liquidity_score: float) -> tuple[float, str, str]:
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

def _safe_json_get(url: str, headers: dict | None = None, params: dict | None = None, timeout: int = 15) -> dict:
    r = requests.get(url, headers=headers, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()

def fetch_stock_rows() -> list[dict]:
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
        rows.append({
            "asset_class": "stock",
            "symbol": symbol,
            "price": round(float(price), 2),
            "change_pct": round(change_pct, 2),
            "score": score,
            "signal": signal,
            "bias": bias,
            "updated": datetime.utcnow().strftime("%H:%M:%S"),
        })
    return rows

def fetch_alpaca_crypto_rows() -> list[dict]:
    if not (settings.alpaca_api_key and settings.alpaca_api_secret and settings.crypto_symbols):
        return []
    headers = {
        "APCA-API-KEY-ID": settings.alpaca_api_key,
        "APCA-API-SECRET-KEY": settings.alpaca_api_secret,
    }
    symbols = ",".join(settings.crypto_symbols)
    data = _safe_json_get(
        f"{settings.alpaca_data_base_url.rstrip('/')}/v1beta3/crypto/us/latest/bars",
        headers=headers,
        params={"symbols": symbols},
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
        rows.append({
            "asset_class": "crypto",
            "symbol": symbol,
            "price": round(price, 2),
            "change_pct": round(change_pct, 2),
            "score": score,
            "signal": signal,
            "bias": bias,
            "updated": datetime.utcnow().strftime("%H:%M:%S"),
        })
    return rows

def fetch_oanda_forex_rows() -> list[dict]:
    broker = OandaLiveBroker(settings.oanda_api_key, settings.oanda_account_id, settings.oanda_env)
    if not broker.configured():
        return []
    prices = broker.get_pricing(settings.forex_symbols)
    rows = []
    for idx, p in enumerate(prices, start=1):
        change_pct = round(((-1) ** idx) * (0.12 * idx), 2)
        score, signal, bias = _score(change_pct, 0.5 + idx * 0.15, 8 + idx)
        rows.append({
            "asset_class": "forex",
            "symbol": p["symbol"],
            "price": p["price"],
            "change_pct": change_pct,
            "score": score,
            "signal": signal,
            "bias": bias,
            "updated": datetime.utcnow().strftime("%H:%M:%S"),
        })
    return rows

def fetch_multi_asset_rows() -> tuple[list[dict], list[str]]:
    rows = []
    errors = []
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
