"""Open-source model calls (portfolio summary + insights).

Talks to any OpenAI-compatible server: Ollama, vLLM, llama.cpp server, or a
DigitalOcean-hosted open-weight model. If the model is down or slow, we fall
back to a template so the demo never stalls.
"""
from __future__ import annotations

import json
import logging

from openai import OpenAI

from .config import Settings

log = logging.getLogger(__name__)

VOICE_RULES = (
    "Your words will be spoken aloud by a voice assistant. "
    "Write plain sentences only: no markdown, lists, emoji or symbols other than $ and %. "
    "Round dollars to cents and percentages to whole numbers. "
    "Never invent numbers that are not in the data."
)

SUMMARY_PROMPT = (
    "You are a friendly portfolio briefer. Given a JSON portfolio snapshot, give a spoken "
    "briefing in at most 60 words: total value, the largest holding and its share, and how "
    "much cash is available to trade. " + VOICE_RULES
)

INSIGHTS_PROMPT = (
    "You are an educational portfolio coach, not a financial advisor. Given a JSON portfolio "
    "snapshot, give two or three short observations about diversification, concentration or "
    "cash level, each with one idea the user could consider. Do not tell the user to buy or "
    "sell anything specific. At most 80 words. End with: This is not financial advice. "
    + VOICE_RULES
)


class LLM:
    def __init__(self, s: Settings):
        self.s = s
        self.client = OpenAI(base_url=s.llm_base_url, api_key=s.llm_api_key, timeout=s.llm_timeout_seconds, max_retries=0)

    def _ask(self, system: str, data: dict) -> str | None:
        try:
            r = self.client.chat.completions.create(
                model=self.s.llm_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(data)},
                ],
                temperature=0.3,
                max_tokens=220,
            )
            text = (r.choices[0].message.content or "").strip()
            return text or None
        except Exception as e:  # network, timeout, model missing
            log.warning("LLM call failed, using fallback: %s", e)
            return None

    def summary(self, snap: dict) -> dict:
        text = self._ask(SUMMARY_PROMPT, snap)
        return {"text": text or fallback_summary(snap), "source": "llm" if text else "fallback"}

    def insights(self, snap: dict) -> dict:
        text = self._ask(INSIGHTS_PROMPT, snap)
        return {"text": text or fallback_insights(snap), "source": "llm" if text else "fallback"}


def fallback_summary(snap: dict) -> str:
    total = snap.get("total_usd", 0)
    positions = snap.get("positions", [])
    if not positions:
        return "Your portfolio is empty right now."
    invested = [p for p in positions if p["symbol"] != "USDC"]
    cash = f"You have ${snap.get('cash_usd', 0):,.2f} in cash available to trade."
    if not invested:
        return f"Your portfolio is worth ${total:,.2f}, all in cash. {cash}"
    top = invested[0]
    return (
        f"Your portfolio is worth ${total:,.2f}. "
        f"Your largest investment is {top['symbol']}, at {top['weight_pct']:.0f}% of the total. {cash}"
    )


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
