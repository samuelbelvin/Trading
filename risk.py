from __future__ import annotations
from config import settings
from execution.base import OrderRequest

def check_risk(order: OrderRequest, open_positions: list[dict], realized_daily_pnl_pct: float) -> tuple[bool, str]:
    if settings.kill_switch:
        return False, "Kill switch is enabled."
    if realized_daily_pnl_pct <= -abs(settings.max_daily_loss_pct):
        return False, "Daily loss limit reached."
    tracked = {p.get("symbol") for p in open_positions if p.get("symbol")}
    if len(open_positions) >= settings.max_open_positions and order.symbol not in tracked:
        return False, "Maximum open positions reached."
    if (order.notional_usd or 0) <= 0 and (order.qty or 0) <= 0:
        return False, "Order needs qty or notional_usd."
    if (order.notional_usd or 0) > settings.default_order_size_usd:
        return False, f"Order notional exceeds configured default size {settings.default_order_size_usd:.2f}."
    return True, "Risk check passed."
