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

from .broker import BrokerError, make_broker
from .config import get_settings
from .devil import Devil
from .llm import LLM
from .portfolio import snapshot
from .resources import Resources
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
desk = TradeDesk(broker, settings)
llm = LLM(settings)
devil = Devil(settings, llm.client)
resources = Resources(settings)


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


class ChallengeBody(BaseModel):
    asset: str
    text: str = ""
    restart: bool = False


# --- routes ---------------------------------------------------------------


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "broker": broker.name,
        "llm_model": settings.llm_model,
        "max_trade_usd": settings.max_trade_usd,
        "allowed_assets": settings.allowed_asset_list,
    }


@app.get("/api/portfolio")
def get_portfolio():
    return snapshot(broker, settings.quote_asset)


@app.get("/api/price/{asset}")
def get_price(asset: str):
    asset = asset.upper()
    price = broker.get_price(asset)
    return {"asset": asset, "price_usd": price, "say": f"{asset} is at ${price:,.2f}."}


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



# --- devil's advocate -----------------------------------------------------


@app.post("/api/devil/challenge")
def devil_challenge(body: ChallengeBody):
    """Send the user's thesis (first call) or their answer (later calls); get the next question."""
    return devil.challenge(body.asset, body.text[:1200], body.restart)


@app.get("/api/devil")
def devil_state():
    return devil.state()


@app.post("/api/devil/reset")
def devil_reset():
    devil.reset()
    return {"ok": True}


# --- resources ------------------------------------------------------------


@app.get("/api/resources/{asset}")
def gather_resources(asset: str):
    """Vetted sources plus recent SEC filings that mention the asset (live from EDGAR)."""
    return resources.gather(asset)


@app.get("/api/resources")
def last_resources():
    return resources.last or {"asset": None}
