from __future__ import annotations
import requests
from execution.base import OrderRequest, OrderResult

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
            return OrderResult(False, self.name, "", "rejected", "OANDA adapter here supports forex only.")

        units = order.qty
        if units is None:
            if not order.notional_usd:
                return OrderResult(False, self.name, "", "rejected", "Forex order needs qty or notional_usd.")
            units = int(max(1, round(order.notional_usd)))
        units = int(abs(units)) if order.side.lower() == "buy" else -int(abs(units))

        payload = {
            "order": {
                "type": "MARKET",
                "instrument": order.symbol,
                "units": str(units),
                "timeInForce": "FOK",
                "positionFill": "DEFAULT",
            }
        }
        try:
            r = requests.post(f"{self.base_url}/v3/accounts/{self.account_id}/orders", headers=self._headers(), json=payload, timeout=15)
            r.raise_for_status()
            data = r.json()
            txn = data.get("orderFillTransaction") or data.get("orderCreateTransaction") or {}
            return OrderResult(True, self.name, str(txn.get("id", "")), "submitted", "OANDA market order submitted.")
        except Exception as exc:
            return OrderResult(False, self.name, "", "error", str(exc))
