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
    ref: str | None = None  # broker's own id for the prepared order, if any


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

    def get_change_24h(self, asset: str) -> float | None:
        """Percent price change over the last 24 hours, or None if unknown."""
        return None


# ---------------------------------------------------------------------------
# Mock broker
# ---------------------------------------------------------------------------

_MOCK_BASE_PRICES = {"BTC": 67_000.0, "ETH": 2_600.0, "SOL": 150.0, "USDC": 1.0}
_MOCK_CHANGE_24H = {"BTC": 2.1, "ETH": -1.4, "SOL": 3.6}


class MockBroker(Broker):
    """Practice portfolio: fake balances, no orders sent.

    With a live `price_source` (True Markets), prices, quotes and 24h moves are
    real, so practice trades happen at real market prices. If the live source
    fails, it falls back to drifting demo prices so the demo never breaks.
    """

    name = "mock"

    def __init__(self, quote_asset: str = "USDC", price_source=None):
        self.quote_asset = quote_asset
        self.price_source = price_source
        self._lock = threading.Lock()
        self._holdings = {"USDC": 30.0, "BTC": 0.00012, "ETH": 0.0021}
        self.last_price_source = "truemarkets" if price_source else "mock"

    def get_price(self, asset: str) -> float:
        asset = asset.upper()
        if self.price_source is not None and asset != self.quote_asset:
            try:
                price = self.price_source.get_price(asset)
                self.last_price_source = "truemarkets"
                return price
            except BrokerError:
                self.last_price_source = "mock"
        return self._mock_price(asset)

    def _mock_price(self, asset: str) -> float:
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

    def get_change_24h(self, asset: str) -> float | None:
        if self.price_source is not None:
            live = self.price_source.get_change_24h(asset)
            if live is not None:
                return live
        return _MOCK_CHANGE_24H.get(asset.upper())

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


class TrueMarketsPrices:
    """Read-only True Markets prices. compute_quote previews a price; it does not place an order."""

    name = "truemarkets"

    def __init__(self, quote_asset: str = "USDC"):
        self.quote_asset = quote_asset
        self.client = None
        self.m = None
        self._Unset = None
        self._init_lock = threading.Lock()
        self._lock = threading.Lock()
        self._price_cache: dict[str, tuple[float, float]] = {}  # asset -> (time, price)
        self._move_cache: dict[str, tuple[float, float | None]] = {}
        self._init_error: tuple[float, str] | None = None

    def _ensure(self) -> None:
        if self.client is not None:
            return
        # Don't rebuild a failing client on every call; retry after 60s.
        if self._init_error and time.time() - self._init_error[0] < 60:
            raise BrokerError(self._init_error[1])
        try:
            self._ensure_inner()
            self._init_error = None
        except BrokerError as e:
            self._init_error = (time.time(), str(e))
            raise

    def _ensure_inner(self) -> None:
        with self._init_lock:
            if self.client is not None:
                return
            try:
                from truemarkets import Client
                from truemarkets._generated.gateway import models as m
                from truemarkets._generated.gateway.types import Unset

                _allow_access_token_without_refresh()
            except Exception as e:
                raise BrokerError(f"Could not start the True Markets client: {e}") from e
            self.m = m
            self._Unset = Unset
            try:
                client = Client()
            except Exception as e:
                raise BrokerError(f"Could not start the True Markets client: {e}") from e
            if not client.key_file:
                client.close()
                raise BrokerError(
                    "Set TM_KEY_FILE in backend/.env to the JSON file from truemarkets.co, Settings, API Keys. "
                    "Live prices need that key. Trades stay on the mock portfolio and no order is sent."
                )
            self.client = client

    def get_price(self, asset: str) -> float:
        asset = asset.upper()
        if asset == self.quote_asset:
            return 1.0
        hit = self._price_cache.get(asset)
        if hit and time.time() - hit[0] < 10:  # the UI polls every 5s; don't hammer the API
            return hit[1]
        self._ensure()
        q = self._compute_quote(asset, "buy", 10, "quote")  # $10 preview, no order
        price = self._v(q.price)
        if not price:
            raise BrokerError(f"No price returned for {asset}.")
        self._price_cache[asset] = (time.time(), float(price))
        return float(price)

    def get_change_24h(self, asset: str) -> float | None:
        """24h % change from True Markets' public market-data candles (no key needed). None on failure."""
        asset = asset.upper()
        hit = self._move_cache.get(asset)
        if hit and time.time() - hit[0] < 60:
            return hit[1]
        change = None
        try:
            from truemarkets.config import Config
            from truemarkets._generated.marketdata.api.prices import get_v1_defi_market_prices
            from truemarkets._generated.marketdata.client import Client as MDClient
            from truemarkets._generated.marketdata.types import Unset

            if not hasattr(self, "_md"):
                self._md = MDClient(base_url=Config.from_env().base_url, timeout=8)
            resp = get_v1_defi_market_prices.sync(client=self._md, symbol=asset)
            v = lambda x: None if isinstance(x, Unset) else x  # noqa: E731
            for c in v(getattr(resp, "candles", None)) or []:
                if v(c.interval) == "24h":
                    o, cl = float(v(c.open_price) or 0), float(v(c.close_price) or 0)
                    change = round(100 * (cl / o - 1), 1) if o else None
                    break
        except Exception:
            change = None
        self._move_cache[asset] = (time.time(), change)
        return change

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


class TrueMarketsBroker(TrueMarketsPrices, Broker):
    """Real trading via the `truemarkets` SDK (CeFi market orders against USDC).

    Flow per the SDK: compute_quote (preview) -> create_order -> if the order
    comes back `initialized` with payloads, sign them and execute_order ->
    poll get_order_status.
    """

    name = "truemarkets"

    def get_holdings(self) -> dict[str, float]:
        self._ensure()
        resp = self._call("balances", self.client.gateway.list_balances)
        out: dict[str, float] = {}
        for item in self._v(resp.data) or []:
            sym = (self._v(item.symbol) or "").upper()
            total = float(self._v(item.total) or 0)
            if sym and total > 0:
                out[sym] = out.get(sym, 0) + total
        return out

    def quote(self, asset: str, side: str, usd: float) -> Quote:
        self._ensure()
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
        self._ensure()
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


def _allow_access_token_without_refresh() -> None:
    """Org API keys return an access token and no refresh token. SDK 0.3.0 requires both."""
    from truemarkets._generated.authapi.models.access_tokens_response import AccessTokensResponse

    current = AccessTokensResponse.from_dict
    if getattr(current, "_tm_patched", False):
        return
    raw = current.__func__

    def from_dict(cls, src_dict):
        data = dict(src_dict)
        data.setdefault("refresh_token", "")
        return raw(cls, data)

    from_dict._tm_patched = True
    AccessTokensResponse.from_dict = classmethod(from_dict)


def _fmt(x: float) -> str:
    """Decimal string without scientific notation, max 8 dp."""
    return f"{x:.8f}".rstrip("0").rstrip(".")


# ---------------------------------------------------------------------------
# Tensho broker: trade through the local Tensho wallet server
# ---------------------------------------------------------------------------

STABLES = {"USDC", "PYUSD", "USDG", "USDT"}


class TenshoBroker(Broker):
    """Trades through a running Tensho server (true-markets/examples tensho-wallet).

    Tensho holds the True Markets org key and the wallet signer key, and places
    every order for its signed-in customer as a Gateway user, pinned to the DeFi
    venue. This lets the voice app trade the same wallet the team funded, with
    no mouse: prepare = POST /api/orders (quote, nothing signed), execute =
    POST /api/orders/{id}/execute (signs and submits), then poll the order.
    Tensho re-quotes server-side if the reviewed quote is more than ~20s old.
    """

    name = "tensho"

    def __init__(self, base_url: str, email: str, password: str, asset_map: str, http=None):
        import httpx

        if not (email and password):
            raise BrokerError("Set TENSHO_EMAIL and TENSHO_PASSWORD in backend/.env to use Tensho.")
        self.email, self.password = email, password
        self.http = http or httpx.Client(base_url=base_url.rstrip("/"), timeout=20.0)
        # "BTC=CBBTC@base,SOL=SOL@solana" -> {"BTC": ("CBBTC", "base"), ...}
        self.map: dict[str, tuple[str, str]] = {}
        for pair in asset_map.split(","):
            if "=" in pair:
                ours, theirs = pair.split("=", 1)
                sym, _, chain = theirs.partition("@")
                self.map[ours.strip().upper()] = (sym.strip().upper(), (chain or "solana").strip().lower())
        self._back = {v[0]: k for k, v in self.map.items()}
        self._lock = threading.Lock()
        self._logged_in = False

    # -- http ----------------------------------------------------------------

    def _login(self) -> None:
        r = self.http.post("/api/login", json={"email": self.email, "password": self.password})
        if r.status_code != 200:
            raise BrokerError("Tensho sign-in failed. Check TENSHO_EMAIL and TENSHO_PASSWORD.")
        self._logged_in = True

    def _req(self, method: str, path: str, body: dict | None = None) -> dict:
        try:
            if not self._logged_in:
                self._login()
            r = self.http.request(method, path, json=body)
            if r.status_code == 401:
                self._login()
                r = self.http.request(method, path, json=body)
        except BrokerError:
            raise
        except Exception as e:  # connection refused, timeout
            raise BrokerError("I can't reach the Tensho wallet server. Is it running on port 4747?") from e
        try:
            data = r.json()
        except ValueError:
            data = {}
        if r.status_code >= 400:
            msg = data.get("message") or f"error {r.status_code}"
            if "insufficient" in msg.lower():
                msg = "There isn't enough balance in the wallet for that."
            raise BrokerError(msg)
        return data

    def _asset(self, asset: str) -> dict:
        asset = asset.upper()
        if asset not in self.map:
            raise BrokerError(f"{asset} isn't set up for trading in Tensho.")
        sym, chain = self.map[asset]
        for a in self._req("GET", "/api/assets"):
            if a.get("symbol", "").upper() == sym and (a.get("chain") or "solana") == chain and not a.get("cash"):
                return a
        raise BrokerError(f"Tensho doesn't offer {sym} on {chain}. Add it to Tensho's TM_TOKENS.")

    # -- interface -----------------------------------------------------------

    def get_price(self, asset: str) -> float:
        if asset.upper() in STABLES:
            return 1.0
        price = self._asset(asset).get("price")
        if not price:
            raise BrokerError(f"No price for {asset} right now.")
        return float(price)

    def get_holdings(self) -> dict[str, float]:
        p = self._req("GET", "/api/portfolio")
        out: dict[str, float] = {}
        for b in p.get("balances", []):
            sym = (b.get("symbol") or "").upper()
            qty = float(b.get("total") or 0)
            if sym and qty > 0:
                key = self._back.get(sym, sym)
                out[key] = out.get(key, 0.0) + qty
        return out

    def quote(self, asset: str, side: str, usd: float) -> Quote:
        a = self._asset(asset)
        price = float(a.get("price") or 0)
        if side == "buy":
            amount = _fmt(usd)
        else:
            if not price:
                raise BrokerError(f"No price for {asset} right now.")
            amount = _fmt(usd / price)
        order = self._req("POST", "/api/orders", {"asset_id": a["asset_id"], "side": side, "amount": amount})
        q = order.get("quote") or {}
        if side == "buy":
            base_qty = float(q.get("qty_out") or 0)
            price = usd / base_qty if base_qty else price
        else:
            base_qty = float(amount)
        if not order.get("order_id") or base_qty <= 0:
            raise BrokerError(f"Could not get a usable quote for {asset}.")
        return Quote(asset=asset.upper(), side=side, usd=usd, base_qty=base_qty, price=price, ref=order["order_id"])

    def execute(self, q: Quote) -> Fill:
        if not q.ref:
            raise BrokerError("That quote has no order to place. Ask me again.")
        with self._lock:
            res = self._req("POST", f"/api/orders/{q.ref}/execute")
            order_id = res.get("order_id") or q.ref
            status = res.get("status") or "pending"
            detail: dict = {}
            deadline = time.time() + 15
            while status not in ("complete", "failed", "canceled") and time.time() < deadline:
                time.sleep(1.0)
                try:
                    detail = self._req("GET", f"/api/orders/{order_id}")
                    status = detail.get("status") or status
                except BrokerError:
                    pass
            if status in ("complete",) and not detail:
                detail = self._req("GET", f"/api/orders/{order_id}")
        if status == "failed":
            raise BrokerError("The order failed on True Markets. Nothing was bought.")
        base_qty = float(detail.get("executed_qty") or q.base_qty)
        price = float(detail.get("executed_vwap") or q.price)
        return Fill(order_id=order_id, status=status, asset=q.asset, side=q.side, usd=q.usd, base_qty=base_qty, price=price)


def make_broker(mode: str, quote_asset: str, market=None) -> Broker:
    """Trading. live = real True Markets orders. tensho = the team's Tensho wallet server.
    mock = practice portfolio priced by `market` (live True Markets prices when MARKET_MODE=live)."""
    if mode == "tensho":
        from .config import get_settings

        st = get_settings()
        return TenshoBroker(st.tensho_url, st.tensho_email, st.tensho_password, st.tensho_asset_map)
    if mode == "live":
        return TrueMarketsBroker(quote_asset=quote_asset)
    live_prices = market if isinstance(market, TrueMarketsPrices) else None
    return MockBroker(quote_asset=quote_asset, price_source=live_prices)


def make_market(mode: str, quote_asset: str):
    """Price source. Live mode only calls compute_quote; it has no execute method."""
    if mode == "live":
        return TrueMarketsPrices(quote_asset=quote_asset)
    return MockBroker(quote_asset=quote_asset)
