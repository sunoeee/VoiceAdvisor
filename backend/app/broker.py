"""Broker layer: one interface, two implementations.

- MockBroker: fake balances and prices so the team can build without keys.
- TrueMarketsBroker: real trades through the True Markets Gateway SDK.

Everything above this file (trade desk, API, frontend) only talks to the
`Broker` interface, so switching BROKER_MODE=mock -> live changes nothing else.
"""
from __future__ import annotations

import math
import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass


class BrokerError(Exception):
    """A broker call failed; message is safe to show / speak to the user."""


@dataclass
class Quote:
    asset: str
    side: str  # "buy" | "sell"
    usd: float  # notional in quote asset (USDC)
    base_qty: float  # estimated asset quantity
    price: float  # USD per 1 unit of asset


@dataclass
class Fill:
    order_id: str
    status: str
    asset: str
    side: str
    usd: float
    base_qty: float
    price: float


class Broker(ABC):
    name: str = "base"

    @abstractmethod
    def get_price(self, asset: str) -> float: ...

    @abstractmethod
    def get_holdings(self) -> dict[str, float]:
        """Symbol -> total quantity held."""

    @abstractmethod
    def quote(self, asset: str, side: str, usd: float) -> Quote: ...

    @abstractmethod
    def execute(self, q: Quote) -> Fill: ...


# ---------------------------------------------------------------------------
# Mock broker
# ---------------------------------------------------------------------------

_MOCK_BASE_PRICES = {"BTC": 67_000.0, "ETH": 2_600.0, "SOL": 150.0, "USDC": 1.0}


class MockBroker(Broker):
    """In-memory portfolio. Prices drift slightly over time so the UI looks alive."""

    name = "mock"

    def __init__(self, quote_asset: str = "USDC"):
        self.quote_asset = quote_asset
        self._lock = threading.Lock()
        self._holdings = {"USDC": 30.0, "BTC": 0.00012, "ETH": 0.0021}

    def get_price(self, asset: str) -> float:
        asset = asset.upper()
        if asset not in _MOCK_BASE_PRICES:
            raise BrokerError(f"No price available for {asset}.")
        base = _MOCK_BASE_PRICES[asset]
        if asset == self.quote_asset:
            return base
        # +/- 1.5% slow sine drift, different phase per asset
        phase = sum(map(ord, asset))
        return round(base * (1 + 0.015 * math.sin(time.time() / 60 + phase)), 2)

    def get_holdings(self) -> dict[str, float]:
        with self._lock:
            return {k: v for k, v in self._holdings.items() if v > 0}

    def quote(self, asset: str, side: str, usd: float) -> Quote:
        price = self.get_price(asset)
        return Quote(asset=asset, side=side, usd=usd, base_qty=usd / price, price=price)

    def execute(self, q: Quote) -> Fill:
        with self._lock:
            if q.side == "buy":
                if self._holdings.get(self.quote_asset, 0) < q.usd:
                    raise BrokerError(f"Not enough {self.quote_asset} to buy ${q.usd:.2f} of {q.asset}.")
                self._holdings[self.quote_asset] -= q.usd
                self._holdings[q.asset] = self._holdings.get(q.asset, 0) + q.base_qty
            else:
                if self._holdings.get(q.asset, 0) < q.base_qty * 0.999:
                    raise BrokerError(f"Not enough {q.asset} to sell ${q.usd:.2f}.")
                self._holdings[q.asset] = max(0.0, self._holdings.get(q.asset, 0) - q.base_qty)
                self._holdings[self.quote_asset] = self._holdings.get(self.quote_asset, 0) + q.usd
        return Fill(
            order_id=f"mock-{uuid.uuid4().hex[:8]}",
            status="complete",
            asset=q.asset,
            side=q.side,
            usd=q.usd,
            base_qty=q.base_qty,
            price=q.price,
        )


# ---------------------------------------------------------------------------
# True Markets broker
# ---------------------------------------------------------------------------


class TrueMarketsBroker(Broker):
    """Real trading via the `truemarkets` SDK (CeFi market orders against USDC).

    Flow per the SDK: compute_quote (preview) -> create_order -> if the order
    comes back `initialized` with payloads, sign them and execute_order ->
    poll get_order_status.
    """

    name = "truemarkets"

    def __init__(self, quote_asset: str = "USDC"):
        # Imported lazily so mock mode works without the SDK configured.
        from truemarkets import Client
        from truemarkets._generated.gateway import models as m
        from truemarkets._generated.gateway.types import Unset

        self.quote_asset = quote_asset
        self.m = m
        self._Unset = Unset
        try:
            self.client = Client()
        except Exception as e:
            raise BrokerError(f"Could not start the True Markets client: {e}") from e
        self._lock = threading.Lock()

    # -- helpers -------------------------------------------------------------

    def _v(self, x):
        return None if isinstance(x, self._Unset) else x

    def _call(self, what: str, fn, *args, **kwargs):
        """Run an SDK call; turn any SDK/network exception into a BrokerError."""
        try:
            resp = fn(*args, **kwargs)
        except BrokerError:
            raise
        except Exception as e:  # NotAuthenticated, httpx errors, timeouts...
            raise BrokerError(f"True Markets {what} failed: {type(e).__name__}: {e}") from e
        return self._check(resp, what)

    def _check(self, resp, what: str):
        if resp is None:
            raise BrokerError(f"True Markets returned no response for {what}.")
        if isinstance(resp, self.m.ErrorResponse):
            msg = self._v(resp.message) or "unknown error"
            raise BrokerError(f"True Markets {what} failed: {msg}")
        return resp

    def _compute_quote(self, asset: str, side: str, qty: float, unit: str):
        m = self.m
        return self._call(
            "quote",
            self.client.gateway.compute_quote,
            body=m.QuoteRequest(
                base_asset=asset,
                quote_asset=self.quote_asset,
                qty=_fmt(qty),
                qty_unit=m.QuoteRequestQtyUnit(unit),
                side=m.OrderSide(side),
            ),
        )

    # -- interface -----------------------------------------------------------

    def get_price(self, asset: str) -> float:
        asset = asset.upper()
        if asset == self.quote_asset:
            return 1.0
        q = self._compute_quote(asset, "buy", 10, "quote")  # $10 preview
        price = self._v(q.price)
        if not price:
            raise BrokerError(f"No price returned for {asset}.")
        return float(price)

    def get_holdings(self) -> dict[str, float]:
        resp = self._call("balances", self.client.gateway.list_balances)
        out: dict[str, float] = {}
        for item in self._v(resp.data) or []:
            sym = (self._v(item.symbol) or "").upper()
            total = float(self._v(item.total) or 0)
            if sym and total > 0:
                out[sym] = out.get(sym, 0) + total
        return out

    def quote(self, asset: str, side: str, usd: float) -> Quote:
        if side == "buy":
            q = self._compute_quote(asset, "buy", usd, "quote")
            base_qty = float(self._v(q.qty) or 0)
            price = float(self._v(q.price) or 0) or (usd / base_qty if base_qty else 0)
        else:
            price = self.get_price(asset)
            base_qty = usd / price
            q = self._compute_quote(asset, "sell", base_qty, "base")
            price = float(self._v(q.price) or price)
        if base_qty <= 0 or price <= 0:
            raise BrokerError(f"Could not get a usable quote for {asset}.")
        return Quote(asset=asset, side=side, usd=usd, base_qty=base_qty, price=price)

    def execute(self, q: Quote) -> Fill:
        m = self.m
        with self._lock:
            if q.side == "buy":
                qty, unit = _fmt(q.usd), m.CreateOrderRequestQtyUnit.QUOTE
            else:
                qty, unit = _fmt(q.base_qty), m.CreateOrderRequestQtyUnit.BASE
            order = self._call(
                "order",
                self.client.gateway.create_order,
                body=m.CreateOrderRequest(
                    base_asset=q.asset,
                    quote_asset=self.quote_asset,
                    qty=qty,
                    qty_unit=unit,
                    type_=m.OrderType.MARKET,
                    side=m.OrderSide(q.side),
                ),
            )
            order_id = self._v(order.order_id)
            if not order_id:
                raise BrokerError("True Markets did not return an order id.")

            status = self._v(order.status)
            payloads = self._v(order.payloads) or []
            if payloads and status in (None, m.OrderStatus.INITIALIZED):
                stamps = [self.client.sign_turnkey(p.payload) for p in payloads]
                self._call(
                    "order execution",
                    self.client.gateway.execute_order,
                    order_id,
                    body=m.ExecuteOrderRequest(signatures=stamps, auth_type=m.SigningMethod.API_KEY),
                )

            final = self._poll(order_id)
        return Fill(
            order_id=order_id,
            status=final,
            asset=q.asset,
            side=q.side,
            usd=q.usd,
            base_qty=q.base_qty,
            price=q.price,
        )

    def _poll(self, order_id: str, timeout: float = 8.0) -> str:
        terminal = {"complete", "failed", "canceled"}
        deadline = time.time() + timeout
        status = "pending"
        while time.time() < deadline:
            try:
                resp = self.client.gateway.get_order_status(order_id)
            except Exception:  # transient; keep polling
                resp = None
            if resp is not None and not isinstance(resp, self.m.ErrorResponse):
                s = self._v(resp.status)
                status = s.value if s is not None else status
                if status in terminal:
                    break
            time.sleep(0.75)
        if status == "failed":
            raise BrokerError("The order failed on True Markets.")
        return status


def _fmt(x: float) -> str:
    """Decimal string without scientific notation, max 8 dp."""
    return f"{x:.8f}".rstrip("0").rstrip(".")


def make_broker(mode: str, quote_asset: str) -> Broker:
    if mode == "live":
        return TrueMarketsBroker(quote_asset=quote_asset)
    return MockBroker(quote_asset=quote_asset)
