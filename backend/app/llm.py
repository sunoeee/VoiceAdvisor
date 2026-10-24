"""Open-source model calls: morning brief, insights, and investment guidance.

Talks to any OpenAI-compatible server: Ollama, vLLM, llama.cpp server, or a
DigitalOcean-hosted open-weight model. If the model is down or slow, each call
falls back to a template so the demo never stalls.
"""
from __future__ import annotations

import json
import logging

from openai import OpenAI

from .advice import fallback_guidance
from .config import Settings

log = logging.getLogger(__name__)

VOICE_RULES = (
    "Your words will be spoken aloud by a voice assistant. "
    "Write plain sentences only: no markdown, lists, headings, emoji or symbols other than $ and %. "
    "Round dollars to cents and percentages to whole numbers. "
    "Use only numbers that appear in the data. Never invent prices, news, earnings or forecasts."
)

BRIEF_PROMPT = (
    "You are Ticker, a warm, upbeat assistant giving the user their good morning portfolio brief. "
    "Given JSON with the portfolio snapshot and each holding's 24-hour price change, speak at most 70 words: "
    "greet them, give the total value, mention the biggest mover (up or down) with its percent change, "
    "name the largest holding and its share, and say how much cash is available. "
    "End by asking if they'd like to make any moves today. " + VOICE_RULES
)

INSIGHTS_PROMPT = (
    "You are an educational portfolio coach, not a financial advisor. Given a JSON portfolio "
    "snapshot, give two or three short observations about diversification, concentration or "
    "cash level, each with one idea the user could consider. Do not tell the user to buy or "
    "sell anything specific. At most 80 words. End with: This is not financial advice. "
    + VOICE_RULES
)

GUIDANCE_PROMPT = (
    "You are Ticker, an educational investing guide, not a licensed financial advisor. "
    "The user is considering an investment and asked the question in the JSON. The JSON also holds "
    "their portfolio and pre-computed facts about how this investment would change it. "
    "In at most 110 words: "
    "first, one sentence restating what they're considering and what share of their portfolio it is; "
    "second, one or two potential upsides, stated generally and tied to the asset type; "
    "third, the two most important risks, using the facts provided (concentration, sector exposure, cash, volatility); "
    "fourth, ask exactly one guiding question, chosen from suggested_questions or similar, that helps them decide. "
    "Never tell them to buy or sell, never predict prices, and never claim to know current news about the company. "
    "If the asset is not tradeable in this app, say so briefly. "
    "End with: This is educational guidance, not financial advice. " + VOICE_RULES
)


class LLM:
    def __init__(self, s: Settings):
        self.s = s
        # max_retries=0: fail fast to the template instead of retrying a slow model
        self.client = OpenAI(
            base_url=s.llm_base_url, api_key=s.llm_api_key, timeout=s.llm_timeout_seconds, max_retries=0
        )

    def _ask(self, system: str, data: dict, max_tokens: int = 220) -> str | None:
        try:
            r = self.client.chat.completions.create(
                model=self.s.llm_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(data)},
                ],
                temperature=0.3,
                max_tokens=max_tokens,
            )
            text = (r.choices[0].message.content or "").strip()
            return text or None
        except Exception as e:  # network, timeout, model missing
            log.warning("LLM call failed, using fallback: %s", e)
            return None

    def morning_brief(self, snap: dict, moves: dict[str, float | None]) -> dict:
        data = {"portfolio": snap, "change_24h_pct": {k: v for k, v in moves.items() if v is not None}}
        text = self._ask(BRIEF_PROMPT, data)
        return {"text": text or fallback_brief(snap, moves), "source": "llm" if text else "fallback"}

    # Kept for compatibility with the original summary endpoint
    def summary(self, snap: dict) -> dict:
        return self.morning_brief(snap, {})

    def insights(self, snap: dict) -> dict:
        text = self._ask(INSIGHTS_PROMPT, snap)
        return {"text": text or fallback_insights(snap), "source": "llm" if text else "fallback"}

    def guidance(self, ctx: dict) -> dict:
        text = self._ask(GUIDANCE_PROMPT, ctx, max_tokens=300)
        return {"text": text or fallback_guidance(ctx), "source": "llm" if text else "fallback"}


def fallback_brief(snap: dict, moves: dict[str, float | None]) -> str:
    total = snap.get("total_usd", 0)
    positions = snap.get("positions", [])
    if not positions:
        return "Good morning. Your portfolio is empty right now."
    parts = [f"Good morning. Your portfolio is worth ${total:,.2f}."]
    known = {k: v for k, v in moves.items() if v is not None}
    if known:
        sym, chg = max(known.items(), key=lambda kv: abs(kv[1]))
        parts.append(f"{sym} is {'up' if chg >= 0 else 'down'} {abs(chg):.0f}% since yesterday.")
    invested = [p for p in positions if p["symbol"] != "USDC"]
    if invested:
        top = invested[0]
        parts.append(f"Your largest investment is {top['symbol']}, at {top['weight_pct']:.0f}% of the total.")
    parts.append(f"You have ${snap.get('cash_usd', 0):,.2f} in cash available. Any moves today?")
    return " ".join(parts)


def fallback_summary(snap: dict) -> str:  # backwards compatible name
    return fallback_brief(snap, {})


def fallback_insights(snap: dict) -> str:
    positions = [p for p in snap.get("positions", []) if p["symbol"] != "USDC"]
    total = snap.get("total_usd", 0) or 1
    cash_pct = 100 * snap.get("cash_usd", 0) / total
    parts = []
    if positions and positions[0]["weight_pct"] > 50:
        parts.append(f"{positions[0]['symbol']} makes up most of your invested money, so its swings drive your results.")
    if cash_pct > 50:
        parts.append(f"About {cash_pct:.0f}% is in cash, which keeps risk low but means less exposure to gains.")
    if len(positions) <= 1:
        parts.append("Holding more than one asset could spread out your risk.")
    if not parts:
        parts.append("Your holdings look fairly balanced across assets and cash.")
    return " ".join(parts) + " This is not financial advice."
