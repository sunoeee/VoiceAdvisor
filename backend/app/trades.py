"""Trade desk: the only path to moving money.

The voice agent can *ask* for a trade, but every rule lives here:
- asset allowlist, per-trade cap, daily cap, balance check
- a quote must be prepared and read back before it can be executed
- confirmations expire and are single-use
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date

from .broker import Broker, BrokerError, Quote
from .config import Settings


class TradeError(Exception):
    """A rule blocked the trade. Message is written to be spoken aloud."""


@dataclass
class PendingTrade:
    confirmation_id: str
    quote: Quote
    expires_at: float


@dataclass
class TradeRecord:
    order_id: str
    status: str
    asset: str
    side: str
    usd: float
    base_qty: float
    price: float
    at: float = field(default_factory=time.time)


class TradeDesk:
    def __init__(self, broker: Broker, settings: Settings):
        self.broker = broker
        self.s = settings
        self._lock = threading.Lock()
        self._pending: dict[str, PendingTrade] = {}
        self.log: list[TradeRecord] = []
        self._spent_day = date.today()
        self._spent_usd = 0.0

    # -- rules ---------------------------------------------------------------

    def _spent_today(self) -> float:
        if self._spent_day != date.today():
            self._spent_day, self._spent_usd = date.today(), 0.0
        return self._spent_usd

    def _validate(self, asset: str, side: str, usd: float) -> tuple[str, str, float]:
        asset = (asset or "").strip().upper()
        side = (side or "").strip().lower()
        if side not in ("buy", "sell"):
            raise TradeError("I can only buy or sell.")
        if asset not in self.s.allowed_asset_list:
            allowed = ", ".join(self.s.allowed_asset_list)
            raise TradeError(f"I can only trade {allowed} right now.")
        try:
            usd = round(float(usd), 2)
        except (TypeError, ValueError):
            raise TradeError("I didn't catch the dollar amount.")
        if usd <= 0:
            raise TradeError("The amount needs to be more than zero dollars.")
        if usd > self.s.max_trade_usd:
            raise TradeError(f"For safety, trades are capped at ${self.s.max_trade_usd:.0f} each.")
        left = self.s.daily_limit_usd - self._spent_today()
        if usd > left:
            raise TradeError(f"That would pass today's ${self.s.daily_limit_usd:.0f} limit. You have ${max(left, 0):.2f} left.")
        return asset, side, usd

    def _check_balance(self, q: Quote) -> None:
        holdings = self.broker.get_holdings()
        if q.side == "buy":
            cash = holdings.get(self.s.quote_asset, 0.0)
            if cash < q.usd:
                raise TradeError(f"You only have ${cash:.2f} in {self.s.quote_asset}.")
        else:
            held = holdings.get(q.asset, 0.0)
            if held < q.base_qty * 0.999:
                raise TradeError(f"You only hold about ${held * q.price:.2f} of {q.asset}.")

    # -- public API ----------------------------------------------------------

    def prepare(self, asset: str, side: str, usd: float) -> dict:
        with self._lock:
            asset, side, usd = self._validate(asset, side, usd)
        try:
            q = self.broker.quote(asset, side, usd)
            self._check_balance(q)
        except BrokerError as e:
            raise TradeError(str(e)) from e
        cid = uuid.uuid4().hex[:6]
        with self._lock:
            self._pending = {k: v for k, v in self._pending.items() if v.expires_at > time.time()}
            self._pending[cid] = PendingTrade(cid, q, time.time() + self.s.quote_ttl_seconds)
        verb = "Buy" if side == "buy" else "Sell"
        return {
            "confirmation_id": cid,
            "asset": asset,
            "side": side,
            "usd": usd,
            "est_qty": round(q.base_qty, 8),
            "price_usd": round(q.price, 2),
            "expires_in_seconds": self.s.quote_ttl_seconds,
            "say": (
                f"{verb} {q.base_qty:.6f} {asset} for ${usd:.2f}, at about ${q.price:,.2f} each. "
                f"Say confirm to place it, or cancel. This quote expires in {self.s.quote_ttl_seconds} seconds."
            ),
        }

    def _take(self, confirmation_id: str | None) -> PendingTrade:
        now = time.time()
        live = {k: v for k, v in self._pending.items() if v.expires_at > now}
        cid = (confirmation_id or "").strip().lower()
        if cid and cid in self._pending:
            p = self._pending.pop(cid)
            if p.expires_at <= now:
                raise TradeError("That quote expired. Ask me again and I'll get a fresh price.")
            return p
        # Voice agents sometimes garble ids: fall back to the single live quote.
        if len(live) == 1:
            only = next(iter(live))
            return self._pending.pop(only)
        if not live:
            raise TradeError("There's no trade waiting for confirmation. Tell me what you'd like to trade.")
        raise TradeError("There's more than one trade waiting. Which one should I confirm?")

    def execute(self, confirmation_id: str | None) -> dict:
        with self._lock:
            p = self._take(confirmation_id)
            q = p.quote
            if q.usd > self.s.daily_limit_usd - self._spent_today():
                raise TradeError("That would pass today's limit, so I didn't place it.")
        try:
            fill = self.broker.execute(q)
        except BrokerError as e:
            raise TradeError(str(e)) from e
        with self._lock:
            self._spent_usd += q.usd
            rec = TradeRecord(**asdict(fill))
            self.log.insert(0, rec)
        verb = "Bought" if q.side == "buy" else "Sold"
        done = "Done." if fill.status == "complete" else f"Order is {fill.status}."
        return {
            **asdict(rec),
            "say": f"{done} {verb} {q.base_qty:.6f} {q.asset} for ${q.usd:.2f}.",
        }

    def cancel(self, confirmation_id: str | None) -> dict:
        with self._lock:
            cid = (confirmation_id or "").strip().lower()
            if cid in self._pending:
                self._pending.pop(cid)
            else:
                self._pending.clear()
        return {"say": "Cancelled. Nothing was traded."}

    def pending(self) -> list[dict]:
        now = time.time()
        return [
            {
                "confirmation_id": p.confirmation_id,
                "asset": p.quote.asset,
                "side": p.quote.side,
                "usd": p.quote.usd,
                "est_qty": p.quote.base_qty,
                "price_usd": p.quote.price,
                "expires_in_seconds": max(0, round(p.expires_at - now)),
            }
            for p in self._pending.values()
            if p.expires_at > now
        ]
