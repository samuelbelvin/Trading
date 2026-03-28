from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol

@dataclass
class OrderRequest:
    asset_class: str
    symbol: str
    side: str
    qty: float | None = None
    notional_usd: float | None = None
    order_type: str = "market"
    tif: str = "day"

@dataclass
class OrderResult:
    ok: bool
    broker: str
    order_id: str
    status: str
    message: str

class ExecutionBroker(Protocol):
    name: str
    def place_order(self, order: OrderRequest) -> OrderResult: ...
    def get_positions(self) -> list[dict]: ...
    def get_account(self) -> dict: ...
