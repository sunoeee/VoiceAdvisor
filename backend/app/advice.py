"""Portfolio-impact analysis for "should I invest X in Y?" questions.

All arithmetic happens here, deterministically. The open model only turns these
facts into spoken guidance, so it never has to do math or guess numbers.
"""
from __future__ import annotations

from . import assets


def _category_weights(snap: dict) -> dict[str, float]:
    total = snap.get("total_usd") or 0
    out: dict[str, float] = {}
    tech = 0.0
    for p in snap.get("positions", []):
        cat = assets.info(p["symbol"]).get("category", "unknown")
        out[cat] = out.get(cat, 0) + p["value_usd"]
        if assets.tech_like(p["symbol"]):
            tech += p["value_usd"]
    pct = {k: round(100 * v / total, 1) for k, v in out.items()} if total else {}
    pct["technology"] = round(100 * tech / total, 1) if total else 0.0
    return pct


def analyze(snap: dict, question: str, asset: str | None, usd: float | None, pct: float | None,
            allowed_assets: list[str]) -> dict:
    total = float(snap.get("total_usd") or 0)
    cash = float(snap.get("cash_usd") or 0)
    symbol = assets.resolve(asset)
    a = assets.info(symbol)

    # Amount: dollars win; else derive from percent of portfolio
    amount = float(usd) if usd else (total * float(pct) / 100 if pct and total else None)

    ctx: dict = {
        "question": question,
        "portfolio_total_usd": round(total, 2),
        "cash_usd": round(cash, 2),
        "current_mix_pct": _category_weights(snap),
        "holdings": [
            {"symbol": p["symbol"], "value_usd": p["value_usd"], "weight_pct": p["weight_pct"],
             "category": assets.info(p["symbol"]).get("category")}
            for p in snap.get("positions", [])
        ],
        "asset": a or None,
        "facts": [],
        "suggested_questions": [],
    }
    facts, qs = ctx["facts"], ctx["suggested_questions"]

    if symbol:
        ctx["tradeable_in_this_app"] = symbol in allowed_assets
        if symbol not in allowed_assets:
            ctx["not_tradeable_note"] = f"{a['name']} is not tradeable in this app yet; it currently supports {', '.join(allowed_assets)}."
        if a.get("type") == "single stock":
            facts.append(f"{a['name']} is a single stock, so its price depends heavily on one company's results.")
        elif a.get("category") == "crypto":
            facts.append(f"{a['name']} is a cryptocurrency; crypto prices can move more than 10% in a day.")
        elif a.get("type") == "index fund":
            facts.append(f"{a['name']} is an index fund that spreads money across many companies.")

    if amount is not None and total > 0:
        amount = round(amount, 2)
        existing = next((p["value_usd"] for p in snap.get("positions", []) if p["symbol"] == symbol), 0.0)
        new_weight = round(100 * (existing + amount) / total, 1)
        ctx["amount_usd"] = amount
        ctx["amount_pct_of_portfolio"] = round(100 * amount / total, 1)
        ctx["asset_weight_after_pct"] = new_weight
        ctx["cash_after_usd"] = round(max(cash - amount, 0), 2)

        facts.append(f"${amount:,.2f} is {ctx['amount_pct_of_portfolio']:.0f}% of the ${total:,.2f} portfolio.")
        if amount > cash:
            gap = amount - cash
            ctx["funding_gap_usd"] = round(gap, 2)
            facts.append(f"Only ${cash:,.2f} is in cash, so this needs ${gap:,.2f} more from selling other holdings or a deposit.")
        if symbol:
            if existing:
                facts.append(f"You already hold ${existing:,.2f} of {symbol}; afterwards it would be {new_weight:.0f}% of the portfolio.")
            elif new_weight >= 25:
                facts.append(f"Afterwards {symbol} would be {new_weight:.0f}% of the portfolio, a large share for one asset.")
            mix = ctx["current_mix_pct"]
            if assets.tech_like(symbol):
                tech_after = round(mix.get("technology", 0) + 100 * amount / total, 1)
                facts.append(f"Technology exposure would go from {mix.get('technology', 0):.0f}% to {tech_after:.0f}%.")
            cat = a.get("category")
            if cat in ("crypto", "stock") and total:
                cat_after = round(mix.get(cat, 0) + 100 * amount / total, 1)
                if cat_after >= 60:
                    facts.append(f"{cat.capitalize()} would make up {cat_after:.0f}% of the portfolio.")
        if total and ctx["cash_after_usd"] / total < 0.1:
            facts.append("Cash would drop below 10% of the portfolio.")

    if ctx.get("not_tradeable_note"):
        facts.append(ctx["not_tradeable_note"])

    qs.extend([
        "How long do you plan to hold this: months, or several years?",
        "How would you feel if this investment dropped 30% in a month?",
    ])
    if symbol and (assets.tech_like(symbol) or a.get("category") == "crypto"):
        qs.append("Would you like to spread this amount across a few different assets instead of one?")
    if amount and amount > cash:
        qs.append("Would you start with a smaller amount from your available cash?")
    return ctx


def fallback_guidance(ctx: dict) -> str:
    facts = " ".join(ctx.get("facts", [])[:3]) or "I looked at your portfolio."
    q = (ctx.get("suggested_questions") or ["What's your goal for this money?"])[0]
    return f"{facts} {q} This is educational guidance, not financial advice."
