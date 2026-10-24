"""Gather reading material on an asset: the vetted sources the devil uses, plus
recent SEC filings that mention the asset, pulled live from SEC EDGAR full-text
search. Every item is a real link returned by a source; the model never writes
or picks links. If EDGAR is slow or unreachable, the vetted list still returns.

SEC asks automated clients to send a User-Agent with contact info and to stay
under 10 requests per second; results are cached for 10 minutes.
"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta

import httpx

from .config import Settings
from .devil import load_packets

log = logging.getLogger(__name__)

EDGAR_SEARCH = "https://efts.sec.gov/LATEST/search-index"
SEARCH_TERMS = {"BTC": '"bitcoin"', "ETH": '"ether" "Ethereum"', "SOL": '"Solana"'}
FORMS = "10-K,10-Q,8-K,S-1,424B3"
FORM_NAMES = {
    "10-K": "annual report",
    "10-Q": "quarterly report",
    "8-K": "current report",
    "S-1": "registration statement",
    "424B3": "prospectus",
}
CACHE_SECONDS = 600


def filing_url(cik: str, adsh: str, filename: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{adsh.replace('-', '')}/{filename}"


def parse_edgar(payload: dict, limit: int = 5) -> list[dict]:
    """Turn an EDGAR full-text-search response into resource items (newest first, one per filing)."""
    out, seen = [], set()
    hits = (payload.get("hits") or {}).get("hits") or []
    for h in hits:
        src = h.get("_source") or {}
        _id = h.get("_id") or ""
        adsh, _, filename = _id.partition(":")
        adsh = src.get("adsh") or adsh
        ciks = src.get("ciks") or []
        if not (adsh and filename and ciks) or adsh in seen:
            continue
        seen.add(adsh)
        names = src.get("display_names") or ["Unknown filer"]
        filer = names[0].split("(CIK")[0].strip()
        form = src.get("form") or src.get("file_type") or "filing"
        out.append(
            {
                "title": f"{filer}: {FORM_NAMES.get(form, form)} ({form})",
                "publisher": filer,
                "date": src.get("file_date") or "",
                "url": filing_url(ciks[0], adsh, filename),
                "kind": "sec_filing_live",
            }
        )
    out.sort(key=lambda r: r["date"], reverse=True)
    return out[:limit]


class Resources:
    def __init__(self, s: Settings, http: httpx.Client | None = None):
        self.s = s
        self.http = http or httpx.Client(timeout=6.0, headers={"User-Agent": s.sec_user_agent})
        self.packets = load_packets()
        self.cache: dict[str, tuple[float, list[dict]]] = {}
        self.last: dict | None = None

    def vetted(self, asset: str) -> list[dict]:
        p = self.packets.get(asset)
        if not p:
            return []
        return [
            {"title": s["title"], "publisher": s["publisher"], "date": s["date"], "url": s["url"], "kind": s["type"]}
            for s in p["source_items"]
        ]

    def live(self, asset: str) -> list[dict] | None:
        hit = self.cache.get(asset)
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
        today = date.today()
        params = {
            "q": SEARCH_TERMS[asset],
            "forms": FORMS,
            "dateRange": "custom",
            "startdt": (today - timedelta(days=120)).isoformat(),
            "enddt": today.isoformat(),
        }
        try:
            r = self.http.get(EDGAR_SEARCH, params=params)
            r.raise_for_status()
            items = parse_edgar(r.json())
        except Exception as e:  # network, rate limit, format change
            log.warning("EDGAR search failed for %s: %s", asset, e)
            return None
        self.cache[asset] = (time.time(), items)
        return items

    def gather(self, asset: str) -> dict:
        asset = asset.strip().upper()
        if asset not in SEARCH_TERMS:
            return {"error": "unsupported", "say": f"I can only gather resources for BTC, ETH or SOL right now."}
        vetted = self.vetted(asset)
        live = self.live(asset)
        name = self.packets.get(asset, {}).get("name", asset)
        parts = [f"I've put {len(vetted)} vetted sources on {name} on your screen."]
        if live:
            newest = live[0]
            parts.append(
                f"I also found {len(live)} recent SEC filings that mention {name}. "
                f"The newest is from {newest['publisher']}, filed {newest['date']}."
            )
        elif live is None:
            parts.append("I couldn't reach SEC EDGAR for recent filings just now.")
        else:
            parts.append(f"I didn't find SEC filings mentioning {name} in the last four months.")
        parts.append("These are documents to read, not recommendations.")
        self.last = {"asset": asset, "vetted": vetted, "recent_filings": live or [], "edgar_ok": live is not None, "at": time.time()}
        return {**self.last, "say": " ".join(parts)}
