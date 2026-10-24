"""Hello-world for True Markets credentials. Read-only: places no orders.

Run from backend/:  python scripts/smoke_test_truemarkets.py
Needs TM_KEY_FILE (and optionally TM_ENV) in backend/.env.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.broker import BrokerError, TrueMarketsBroker  # noqa: E402


def main() -> int:
    try:
        b = TrueMarketsBroker()
        print("Holdings:", b.get_holdings() or "(none)")
        for asset in ("BTC", "ETH", "SOL"):
            try:
                print(f"{asset} price: ${b.get_price(asset):,.2f}")
            except BrokerError as e:
                print(f"{asset}: {e}")
        q = b.quote("BTC", "buy", 5)
        print(f"Quote: $5 buys {q.base_qty:.8f} BTC at ${q.price:,.2f}")
        print("\nTrue Markets is working. Set BROKER_MODE=live when you're ready.")
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"FAILED: {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
