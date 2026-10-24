"""Talk-to-Trade API.

Every endpoint returns a `say` field where it makes sense: a sentence the voice
agent can read out verbatim.
"""
from __future__ import annotations

import logging

import httpx

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from . import advice
from .broker import BrokerError, make_broker, make_market
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

# Prices come from True Markets when MARKET_MODE=live. The practice (mock) broker
# uses those live prices too, so the portfolio, brief, guidance and quotes are real.
market = make_market(settings.market_mode, settings.quote_asset)
broker = make_broker(settings.broker_mode, settings.quote_asset, market)
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


class AdviseBody(BaseModel):
    question: str
    asset: str | None = None
    usd_amount: float | None = None
    percent_of_portfolio: float | None = None


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
        "market": market.name,
        "llm_model": settings.llm_model,
        "tts_ready": bool(settings.elevenlabs_api_key),
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


def _change_24h(symbol: str) -> float | None:
    for src in (broker, market):
        fn = getattr(src, "get_change_24h", None)
        if fn:
            v = fn(symbol)
            if v is not None:
                return v
    return None


def _moves(snap: dict) -> dict[str, float | None]:
    return {p["symbol"]: _change_24h(p["symbol"]) for p in snap["positions"] if p["symbol"] != settings.quote_asset}


@app.get("/api/brief")
@app.get("/api/summary")
def get_brief():
    """Good-morning brief: portfolio + 24h moves, written by the open model."""
    snap = snapshot(broker, settings.quote_asset)
    moves = _moves(snap)
    s = llm.morning_brief(snap, moves)
    return {"portfolio": snap, "change_24h_pct": moves, "say": s["text"], "source": s["source"]}


@app.get("/api/insights")
def get_insights():
    snap = snapshot(broker, settings.quote_asset)
    s = llm.insights(snap)
    return {"say": s["text"], "source": s["source"]}


@app.post("/api/advise")
def advise(body: AdviseBody):
    """Educational guidance for 'should I invest X in Y?' questions."""
    snap = snapshot(broker, settings.quote_asset)
    ctx = advice.analyze(snap, body.question, body.asset, body.usd_amount, body.percent_of_portfolio,
                         settings.allowed_asset_list)
    g = llm.guidance(ctx)
    return {"analysis": ctx, "say": g["text"], "source": g["source"]}


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


# --- ElevenLabs read-aloud --------------------------------------------------


class TTSBody(BaseModel):
    text: str


@app.post("/api/tts")
def tts(body: TTSBody):
    """Reads text (e.g. the Ollama-written morning brief) aloud with ElevenLabs. Returns an MP3."""
    if not settings.elevenlabs_api_key:
        return JSONResponse(status_code=500, content={"error": "Set ELEVENLABS_API_KEY in backend/.env"})
    try:
        r = httpx.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{settings.elevenlabs_voice_id}",
            headers={"xi-api-key": settings.elevenlabs_api_key, "Accept": "audio/mpeg"},
            json={"text": body.text[:1500], "model_id": settings.elevenlabs_model_id},
            timeout=30,
        )
    except httpx.HTTPError as e:
        return JSONResponse(status_code=502, content={"error": f"Couldn't reach ElevenLabs: {e}"})
    if r.status_code != 200:
        return JSONResponse(status_code=502, content={"error": r.text[:300]})
    return Response(content=r.content, media_type="audio/mpeg")
