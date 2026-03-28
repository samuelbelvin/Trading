def trade_side_from_row(row: dict) -> str:
    return "buy" if row.get("bias") == "Bullish" else "sell"

def tradable_rows(rows: list[dict], min_score: float = 70) -> list[dict]:
    return [r for r in rows if r.get("score", 0) >= min_score and r.get("signal") in {"Breakout", "Momentum", "A+"}]
