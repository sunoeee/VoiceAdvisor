"""Turn raw holdings into a valued portfolio snapshot."""
from __future__ import annotations

from .broker import Broker, BrokerError


def snapshot(broker: Broker, quote_asset: str = "USDC") -> dict:
    holdings = broker.get_holdings()
    positions = []
    for symbol, qty in sorted(holdings.items()):
        try:
            price = 1.0 if symbol == quote_asset else broker.get_price(symbol)
        except BrokerError:
            price = 0.0
        positions.append(
            {
                "symbol": symbol,
                "qty": qty,
                "price_usd": round(price, 2),
                "value_usd": round(qty * price, 2),
            }
        )
    total = round(sum(p["value_usd"] for p in positions), 2)
    for p in positions:
        p["weight_pct"] = round(100 * p["value_usd"] / total, 1) if total else 0.0
    positions.sort(key=lambda p: p["value_usd"], reverse=True)
    return {
        "total_usd": total,
        "cash_usd": round(holdings.get(quote_asset, 0.0), 2),
        "positions": positions,
        "broker": broker.name,
        # "truemarkets" when values use live True Markets prices, else "mock"
        "price_source": getattr(broker, "last_price_source", broker.name),
    }
