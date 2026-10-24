"""API + guardrail tests. Run from backend/:  pytest -q

Uses the mock broker and a dead LLM URL, so it needs no keys or network.
"""
import os

os.environ["BROKER_MODE"] = "mock"
os.environ["MARKET_MODE"] = "mock"
os.environ["LLM_BASE_URL"] = "http://127.0.0.1:9/v1"  # nothing listens here
os.environ["LLM_TIMEOUT_SECONDS"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402

client = TestClient(main.app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["broker"] == "mock"
    assert r.json()["market"] == "mock"


def test_market_prices_do_not_trade():
    before = len(client.get("/api/trades").json()["history"])
    markets = client.get("/api/markets")
    assert markets.status_code == 200
    body = markets.json()
    assert body["source"] == "mock"
    assert {p["asset"] for p in body["prices"]} == {"BTC", "ETH", "SOL"}
    one = client.get("/api/price/ETH")
    assert one.status_code == 200
    assert one.json()["source"] == "mock"
    assert one.json()["price_usd"] > 0
    assert len(client.get("/api/trades").json()["history"]) == before


def test_portfolio_and_summary_fallback():
    p = client.get("/api/portfolio").json()
    assert p["total_usd"] > 0
    s = client.get("/api/summary").json()
    assert s["source"] == "fallback"
    assert "worth" in s["say"]


def test_buy_flow_requires_confirmation():
    before = client.get("/api/portfolio").json()["cash_usd"]
    prep = client.post("/api/trades/prepare", json={"asset": "eth", "side": "buy", "usd": 5}).json()
    assert prep["confirmation_id"]
    assert client.get("/api/portfolio").json()["cash_usd"] == before  # nothing moved yet
    done = client.post("/api/trades/execute", json={"confirmation_id": prep["confirmation_id"]}).json()
    assert done["status"] == "complete"
    assert client.get("/api/portfolio").json()["cash_usd"] == round(before - 5, 2)


def test_confirmation_is_single_use():
    prep = client.post("/api/trades/prepare", json={"asset": "BTC", "side": "buy", "usd": 1}).json()
    assert client.post("/api/trades/execute", json={"confirmation_id": prep["confirmation_id"]}).status_code == 200
    r = client.post("/api/trades/execute", json={"confirmation_id": prep["confirmation_id"]})
    assert r.status_code == 400


def test_garbled_id_falls_back_to_single_pending():
    client.post("/api/trades/prepare", json={"asset": "BTC", "side": "buy", "usd": 1})
    r = client.post("/api/trades/execute", json={"confirmation_id": "not-a-real-id"})
    assert r.status_code == 200


def test_guardrails():
    assert client.post("/api/trades/prepare", json={"asset": "DOGE", "side": "buy", "usd": 1}).status_code == 400
    assert client.post("/api/trades/prepare", json={"asset": "BTC", "side": "buy", "usd": 50}).status_code == 400
    assert client.post("/api/trades/prepare", json={"asset": "BTC", "side": "short", "usd": 1}).status_code == 400
    assert client.post("/api/trades/prepare", json={"asset": "BTC", "side": "buy", "usd": -3}).status_code == 400
    r = client.post("/api/trades/prepare", json={"asset": "SOL", "side": "sell", "usd": 5})
    assert r.status_code == 400 and "only hold" in r.json()["say"]


def test_cancel():
    client.post("/api/trades/prepare", json={"asset": "BTC", "side": "buy", "usd": 1})
    client.post("/api/trades/cancel", json={})
    assert client.get("/api/trades/pending").json()["pending"] == []
