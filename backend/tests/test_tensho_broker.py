"""TenshoBroker against a fake Tensho server shaped like the real one (no network, no money)."""
import os

os.environ["BROKER_MODE"] = "mock"
os.environ["LLM_BASE_URL"] = "http://127.0.0.1:9/v1"

import httpx  # noqa: E402
import pytest  # noqa: E402

from app.broker import BrokerError, TenshoBroker  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.trades import TradeDesk, TradeError  # noqa: E402

SOL_ID = "495e07ac-fa3e-4179-85b7-b1e8cece3dc4"


class FakeTensho:
    def __init__(self, pyusd="49"):
        self.pyusd = pyusd
        self.calls = []
        self.authed = False

    def __call__(self, req: httpx.Request):
        path, m = req.url.path, req.method
        self.calls.append(f"{m} {path}")
        if path == "/api/login":
            self.authed = True
            return httpx.Response(200, json={"email": "x"})
        if not self.authed:
            return httpx.Response(401, json={"message": "sign in"})
        if path == "/api/assets":
            return httpx.Response(200, json=[
                {"asset_id": SOL_ID, "symbol": "SOL", "chain": "solana", "price": "100.59", "cash": False},
                {"asset_id": "usdc", "symbol": "USDC", "chain": "solana", "price": "1", "cash": True},
            ])
        if path == "/api/portfolio":
            return httpx.Response(200, json={"balances": [
                {"symbol": "PYUSD", "chain": "solana", "total": self.pyusd},
                {"symbol": "SOL", "chain": "solana", "total": "0.009365847"},
            ]})
        if path == "/api/orders" and m == "POST":
            return httpx.Response(200, json={"order_id": "ord-1", "status": "initialized",
                                             "quote": {"base_asset": "SOL", "quote_asset": "USDC", "qty": "1", "qty_out": "0.00991044", "fee": "0.002"}})
        if path == "/api/orders/ord-1/execute":
            return httpx.Response(200, json={"order_id": "ord-1", "status": "pending"})
        if path == "/api/orders/ord-1":
            return httpx.Response(200, json={"order_id": "ord-1", "status": "complete", "executed_qty": "0.009365847", "executed_vwap": "106.77"})
        return httpx.Response(404, json={"message": "not found"})


def broker(fake):
    return TenshoBroker("http://tensho", "a@b.c", "pw", "SOL=SOL@solana,BTC=CBBTC@base",
                        http=httpx.Client(base_url="http://tensho", transport=httpx.MockTransport(fake)))


def test_voice_buy_flow_prepares_then_executes_only_on_confirm():
    fake = FakeTensho()
    s = get_settings().model_copy(update={"quote_asset": "PYUSD"})
    desk = TradeDesk(broker(fake), s)
    prep = desk.prepare("sol", "buy", 1)
    assert "Say confirm" in prep["say"]
    assert not any("execute" in c for c in fake.calls)  # nothing signed or sent on the quote
    done = desk.execute(prep["confirmation_id"])
    assert done["status"] == "complete" and done["base_qty"] == pytest.approx(0.009365847)
    assert "POST /api/orders/ord-1/execute" in fake.calls


def test_pyusd_counts_as_cash_and_sol_is_held():
    b = broker(FakeTensho())
    assert b.get_holdings() == {"PYUSD": 49.0, "SOL": pytest.approx(0.009365847)}
    assert b.get_price("PYUSD") == 1.0 and b.get_price("SOL") == pytest.approx(100.59)


def test_not_enough_cash_is_refused_before_anything_is_prepared_to_execute():
    s = get_settings().model_copy(update={"quote_asset": "PYUSD"})
    desk = TradeDesk(broker(FakeTensho(pyusd="0.5")), s)
    with pytest.raises(TradeError):
        desk.prepare("SOL", "buy", 1)


def test_unconfigured_asset_and_server_down():
    with pytest.raises(BrokerError, match="isn't set up"):
        broker(FakeTensho()).quote("ETH", "buy", 1)
    down = TenshoBroker("http://tensho", "a@b.c", "pw", "SOL=SOL@solana",
                        http=httpx.Client(base_url="http://tensho", transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("refused")))))
    with pytest.raises(BrokerError, match="can't reach the Tensho"):
        down.get_holdings()
