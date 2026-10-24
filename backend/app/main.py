"""Talk-to-Trade API.

Every endpoint returns a `say` field where it makes sense: a sentence the voice
agent can read out verbatim.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .broker import BrokerError, make_broker, make_market
from .config import get_settings
from .llm import LLM
from .portfolio import snapshot
from .trades import TradeDesk, TradeError

logging.basicConfig(level=logging.INFO)
settings = get_settings()

app = FastAPI(title="Talk-to-Trade API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)

broker = make_broker(settings.broker_mode, settings.quote_asset)
market = make_market(settings.market_mode, settings.quote_asset)
desk = TradeDesk(broker, settings)
llm = LLM(settings)


@app.exception_handler(TradeError)
async def trade_error(_: Request, e: TradeError):
    return JSONResponse(status_code=400, content={"error": str(e), "say": str(e)})


@app.exception_handler(BrokerError)
async def broker_error(_: Request, e: BrokerError):
    msg = f"I couldn't reach the exchange: {e}"
    return JSONResponse(status_code=502, content={"error": str(e), "say": msg})


# --- request bodies -------------------------------------------------------


class PrepareBody(BaseModel):
    asset: str
    side: str
    usd: float


class ConfirmBody(BaseModel):
    confirmation_id: str | None = None


# --- routes ---------------------------------------------------------------


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "broker": broker.name,
        "market": market.name,
        "llm_model": settings.llm_model,
        "max_trade_usd": settings.max_trade_usd,
        "allowed_assets": settings.allowed_asset_list,
    }


@app.get("/api/portfolio")
def get_portfolio():
    return snapshot(broker, settings.quote_asset)


def _price_payload(asset: str, price: float) -> dict:
    return {
        "asset": asset,
        "price_usd": price,
        "source": market.name,
        "say": f"{asset} is at ${price:,.2f}.",
    }


@app.get("/api/markets")
def get_markets():
    prices = []
    unavailable = []
    for asset in settings.allowed_asset_list:
        try:
            prices.append(_price_payload(asset, market.get_price(asset)))
        except BrokerError as e:
            unavailable.append({"asset": asset, "error": str(e)})
    if not prices:
        raise BrokerError(unavailable[0]["error"] if unavailable else "No market prices available.")
    spoken = ", ".join(p["say"].removesuffix(".") for p in prices)
    if unavailable:
        skipped = ", ".join(item["asset"] for item in unavailable)
        spoken = f"{spoken}. {skipped} is not available"
    return {"source": market.name, "prices": prices, "unavailable": unavailable, "say": f"{spoken}."}


@app.get("/api/price/{asset}")
def get_price(asset: str):
    asset = asset.upper()
    return _price_payload(asset, market.get_price(asset))


@app.get("/api/summary")
def get_summary():
    snap = snapshot(broker, settings.quote_asset)
    s = llm.summary(snap)
    return {"portfolio": snap, "say": s["text"], "source": s["source"]}


@app.get("/api/insights")
def get_insights():
    snap = snapshot(broker, settings.quote_asset)
    s = llm.insights(snap)
    return {"say": s["text"], "source": s["source"]}


@app.post("/api/trades/prepare")
def prepare_trade(body: PrepareBody):
    return desk.prepare(body.asset, body.side, body.usd)


@app.post("/api/trades/execute")
def execute_trade(body: ConfirmBody):
    return desk.execute(body.confirmation_id)


@app.post("/api/trades/cancel")
def cancel_trade(body: ConfirmBody):
    return desk.cancel(body.confirmation_id)


@app.get("/api/trades")
def list_trades():
    return {"pending": desk.pending(), "history": [vars(r) for r in desk.log]}


@app.get("/api/trades/pending")
def pending_trades():
    return {"pending": desk.pending()}

