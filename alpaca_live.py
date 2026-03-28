from __future__ import annotations
import requests
from execution.base import OrderRequest, OrderResult

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

    def get_positions(self) -> list[dict]:
        if not self.configured():
            return []
        r = requests.get(f"{self.base_url}/v2/positions", headers=self._headers(), timeout=15)
        r.raise_for_status()
        data = r.json()
        rows = []
        for p in data:
            rows.append({
                "symbol": p.get("symbol"),
                "asset_class": p.get("asset_class"),
                "qty": p.get("qty"),
                "side": p.get("side"),
                "market_value": p.get("market_value"),
                "unrealized_pl": p.get("unrealized_pl"),
            })
        return rows

    def place_order(self, order: OrderRequest) -> OrderResult:
        if not self.configured():
            return OrderResult(False, self.name, "", "not_configured", "Missing Alpaca credentials.")
        if order.asset_class not in {"stock", "crypto"}:
            return OrderResult(False, self.name, "", "rejected", "Alpaca adapter here supports stock/crypto only.")
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
