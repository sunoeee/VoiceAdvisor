"""Devil's advocate tests. Run from backend/:  pytest -q  (no keys or network needed)."""
import os

os.environ["BROKER_MODE"] = "mock"
os.environ["LLM_BASE_URL"] = "http://127.0.0.1:9/v1"
os.environ["LLM_TIMEOUT_SECONDS"] = "1"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402
from app.devil import ADVICE, check_reply, find_excerpt, load_packets  # noqa: E402

client = TestClient(main.app)
PACKETS = load_packets()


def test_packets_cover_allowed_assets_and_citations_resolve():
    assert {"BTC", "ETH", "SOL"} <= set(PACKETS)
    for asset, p in PACKETS.items():
        assert len(p["challenges"]) >= 3, asset
        for ch in p["challenges"]:
            assert not ADVICE.search(ch["question"]), ch["id"]
            for c in ch["citations"]:
                assert find_excerpt(p, c["source_id"], c["excerpt_id"]), (asset, ch["id"], c)


def test_three_rounds_then_wrap_up_without_touching_trades():
    client.post("/api/devil/reset")
    cash = client.get("/api/portfolio").json()["cash_usd"]
    r1 = client.post("/api/devil/challenge", json={"asset": "sol", "text": "Visa uses Solana for payments"}).json()
    assert r1["round"] == 1 and r1["source"] == "fallback" and "Visa" in r1["say"]
    r2 = client.post("/api/devil/challenge", json={"asset": "SOL", "text": "Banks settle on it now"}).json()
    assert r2["round"] == 2 and r2["question"] != r1["question"]
    r3 = client.post("/api/devil/challenge", json={"asset": "SOL", "text": "ok"}).json()
    assert r3["round"] == 3
    end = client.post("/api/devil/challenge", json={"asset": "SOL", "text": "fine"}).json()
    assert end["done"] is True and "decision is yours" in end["say"]
    state = client.get("/api/devil").json()
    assert len(state["turns"]) == 3 and state["turns"][0]["citations"][0]["quote"]
    assert client.get("/api/portfolio").json()["cash_usd"] == cash  # the devil never trades


def test_unknown_asset_is_declined_honestly():
    r = client.post("/api/devil/challenge", json={"asset": "DOGE", "text": "to the moon"}).json()
    assert r["done"] is True and "don't have reviewed sources" in r["say"]


def test_model_reply_checks():
    sol = PACKETS["SOL"]
    ok = check_reply({"question": "Visa's run rate covers all settlement. How much is Solana?", "citations": [{"source_id": "S2", "excerpt_id": "E2"}]}, sol)
    assert ok["citations"][0]["source_id"] == "S2"
    with pytest.raises(ValueError):
        check_reply({"question": "What about the roadmap in this filing?", "citations": [{"source_id": "S9", "excerpt_id": "E1"}]}, sol)
    with pytest.raises(ValueError):
        check_reply({"question": "Honestly you should buy now before it runs.", "citations": []}, sol)


class _FakeModel:
    """Stands in for the open model: returns canned replies in order."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.chat = self
        self.completions = self

    def with_options(self, **_):
        return self

    def create(self, **_):
        text = self.replies.pop(0)
        msg = type("M", (), {"content": text})
        return type("R", (), {"choices": [type("C", (), {"message": msg})]})


def test_live_model_question_is_used_and_bad_one_is_replaced():
    from app.config import get_settings
    from app.devil import Devil

    good = '{"question": "Visa\'s run rate covers all its stablecoin settlement. What share is Solana?", "citations": [{"source_id": "S2", "excerpt_id": "E2"}], "open_point": null}'
    invented = '{"question": "The 2027 Solana roadmap says fees drop. Does that matter?", "citations": [{"source_id": "S8", "excerpt_id": "E1"}]}'
    d = Devil(get_settings(), _FakeModel([good, invented]))
    r1 = d.challenge("SOL", "Visa uses it", restart=True)
    assert r1["source"] == "llm" and "What share is Solana" in r1["say"] and "Visa's December 2025 press release" in r1["say"]
    r2 = d.challenge("SOL", "banks settle on it")
    assert r2["source"] == "fallback"  # invented citation rejected, pre-written question used instead
