from __future__ import annotations
from datetime import datetime
from execution.base import OrderRequest, OrderResult

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
