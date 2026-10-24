import { useEffect, useState } from "react";
import type { PendingTrade, Portfolio, TradeRecord } from "./api";

const usd = (n: number) => n.toLocaleString("en-US", { style: "currency", currency: "USD" });
const qty = (n: number) => (n >= 1 ? n.toFixed(4) : n.toPrecision(4));

export function PortfolioCard({ p }: { p: Portfolio | null }) {
  if (!p) return <section className="card">Loading portfolio…</section>;
  return (
    <section className="card">
      <div className="card-head">
        <h2>Portfolio</h2>
        <span className={`badge ${p.broker === "mock" ? "warn" : "live"}`}>
          {p.broker === "mock" ? "Mock data" : "Live · True Markets"}
        </span>
      </div>
      <div className="total">{usd(p.total_usd)}</div>
      <div className="muted">{usd(p.cash_usd)} cash available</div>
      <ul className="positions">
        {p.positions.map((pos) => (
          <li key={pos.symbol}>
            <div className="pos-row">
              <span className="sym">{pos.symbol}</span>
              <span className="mono">{qty(pos.qty)}</span>
              <span className="mono right">{usd(pos.value_usd)}</span>
            </div>
            <div className="bar">
              <div style={{ width: `${pos.weight_pct}%` }} />
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function PendingCard({
  trade,
  onConfirm,
  onCancel,
}: {
  trade: PendingTrade | null;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const [left, setLeft] = useState(0);
  useEffect(() => {
    if (!trade) return;
    setLeft(trade.expires_in_seconds);
    const t = setInterval(() => setLeft((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(t);
  }, [trade]);

  if (!trade) return null;
  return (
    <section className={`card pending ${trade.side}`}>
      <div className="card-head">
        <h2>Awaiting confirmation</h2>
        <span className="mono muted">{left}s</span>
      </div>
      <div className="pending-line">
        <strong>{trade.side === "buy" ? "Buy" : "Sell"}</strong> {qty(trade.est_qty)} {trade.asset} for{" "}
        <strong>{usd(trade.usd)}</strong>
      </div>
      <div className="muted">≈ {usd(trade.price_usd)} per {trade.asset}</div>
      <div className="actions">
        <button className="primary" onClick={onConfirm} disabled={left === 0}>
          Confirm
        </button>
        <button onClick={onCancel}>Cancel</button>
      </div>
      <div className="muted small">Say “confirm” or tap the button.</div>
    </section>
  );
}

export function TradeLog({ history }: { history: TradeRecord[] }) {
  return (
    <section className="card">
      <h2>Trades</h2>
      {history.length === 0 ? (
        <div className="muted">No trades yet. Try “buy five dollars of ETH”.</div>
      ) : (
        <ul className="log">
          {history.map((t) => (
            <li key={t.order_id}>
              <span className={`side ${t.side}`}>{t.side}</span>
              <span>
                {qty(t.base_qty)} {t.asset}
              </span>
              <span className="mono right">{usd(t.usd)}</span>
              <span className="muted small">
                {new Date(t.at * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })} · {t.status}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export type Line = { role: "user" | "agent" | "system"; text: string };

export function Transcript({ lines }: { lines: Line[] }) {
  return (
    <section className="card transcript">
      <h2>Conversation</h2>
      {lines.length === 0 ? (
        <div className="muted">Press Talk and ask “How's my portfolio?”</div>
      ) : (
        <ul>
          {lines.slice(-12).map((l, i) => (
            <li key={i} className={l.role}>
              {l.text}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
