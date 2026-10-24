"""The practice (mock) portfolio must use live True Markets prices when they're available.

Uses a fake price source, so no keys or network are needed.
"""
from app.broker import BrokerError, MockBroker
from app.portfolio import snapshot


class FakeLivePrices:
    name = "truemarkets"

    def __init__(self, fail=False):
        self.fail = fail

    def get_price(self, asset):
        if self.fail:
            raise BrokerError("True Markets unreachable")
        return {"BTC": 100_000.0, "ETH": 4_000.0, "SOL": 200.0}[asset]

    def get_change_24h(self, asset):
        return None if self.fail else {"BTC": 5.0, "ETH": -2.0, "SOL": 1.0}[asset]


def test_practice_portfolio_uses_live_prices():
    b = MockBroker(price_source=FakeLivePrices())
    snap = snapshot(b)
    btc = next(p for p in snap["positions"] if p["symbol"] == "BTC")
    assert btc["price_usd"] == 100_000.0
    assert snap["price_source"] == "truemarkets"
    assert b.get_change_24h("BTC") == 5.0


def test_practice_quotes_use_live_prices():
    b = MockBroker(price_source=FakeLivePrices())
    q = b.quote("ETH", "buy", 8)
    assert q.price == 4_000.0
    assert abs(q.base_qty - 0.002) < 1e-12


def test_falls_back_to_demo_prices_when_live_fails():
    b = MockBroker(price_source=FakeLivePrices(fail=True))
    snap = snapshot(b)
    assert snap["total_usd"] > 0
    assert snap["price_source"] == "mock"
    assert b.get_change_24h("BTC") is not None  # demo move


def test_tts_needs_key():
    import os

    os.environ.setdefault("BROKER_MODE", "mock")
    os.environ.setdefault("MARKET_MODE", "mock")
    from fastapi.testclient import TestClient

    from app import main

    if main.settings.elevenlabs_api_key:
        return  # a real key is configured locally; don't call the API from tests
    r = TestClient(main.app).post("/api/tts", json={"text": "hello"})
    assert r.status_code == 500 and "ELEVENLABS_API_KEY" in r.json()["error"]
