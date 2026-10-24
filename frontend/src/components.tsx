import { useEffect, useState } from "react";
import type { DevilState, Markets, PendingTrade, Portfolio, ResourceItem, ResourceSet, TradeRecord } from "./api";

const usd = (n: number) => n.toLocaleString("en-US", { style: "currency", currency: "USD" });
const qty = (n: number) => (n >= 1 ? n.toFixed(4) : n.toPrecision(4));

export function PortfolioCard({ p }: { p: Portfolio | null }) {
  if (!p) return <section className="card">Loading portfolio…</section>;
  return (
    <section className="card">
      <div className="card-head">
        <h2>Portfolio</h2>
        <span className={`badge ${p.broker === "mock" ? "warn" : "live"}`}>
          {p.broker === "mock" ? "Mock data" : p.broker === "tensho" ? "Live · True Markets wallet" : "Live · True Markets"}
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

export function MarketCard({ markets, liveTrading = false }: { markets: (Markets & { error?: string; say?: string }) | null; liveTrading?: boolean }) {
  if (!markets) return <section className="card">Loading market prices…</section>;
  const live = markets.source === "truemarkets" && !markets.error;
  const badge = markets.error ? "Prices unavailable" : live ? "Live · True Markets" : "Mock prices";
  return (
    <section className="card">
      <div className="card-head">
        <h2>Market prices</h2>
        <span className={`badge ${live ? "live" : "warn"}`}>{badge}</span>
      </div>
      {markets.error ? (
        <div className="muted">{markets.say ?? markets.error}</div>
      ) : (
        <ul className="markets">
          {markets.prices.map((p) => (
            <li key={p.asset}>
              <span className="sym">{p.asset}</span>
              <span className="mono">{usd(p.price_usd)}</span>
            </li>
          ))}
        </ul>
      )}
      {markets.unavailable && markets.unavailable.length > 0 && (
        <div className="muted small">
          {markets.unavailable.map((item) => item.asset).join(", ")} is not available on True Markets.
        </div>
      )}
      {!liveTrading && <div className="muted small">Prices only. Confirming a trade still uses the mock portfolio.</div>}
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
        <div className="muted">No trades yet. Try “buy one dollar of SOL”.</div>
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

export function DevilCard({ d, onReset }: { d: DevilState | null; onReset: () => void }) {
  if (!d?.active) {
    return (
      <section className="card devil">
        <div className="card-head">
          <h2>Devil's advocate</h2>
        </div>
        <p className="muted small">
          Tell Ticker why you like BTC, ETH or SOL and ask it to play devil's advocate. It asks up to three pointed questions,
          each tied to an SEC filing or press release. It never tells you to buy or sell.
        </p>
      </section>
    );
  }
  return (
    <section className="card devil">
      <div className="card-head">
        <h2>Devil's advocate · {d.asset}</h2>
        <button className="link small" onClick={onReset}>
          Clear
        </button>
      </div>
      <p className="thesis">
        <span className="muted small">Your thesis: </span>
        {d.thesis}
      </p>
      <ol className="devil-turns">
        {d.turns?.map((t, i) => (
          <li key={i}>
            <div className="devil-q">
              <span className="side sell">Q{i + 1}</span> {t.question}{" "}
              <span className="badge muted">{t.source === "llm" ? "live AI" : "pre-written"}</span>
            </div>
            {t.citations.map((c) => (
              <blockquote key={c.source_id + c.excerpt_id} className="small">
                “{c.quote}” <span className="muted">— </span>
                <a href={c.url} target="_blank" rel="noreferrer">
                  {c.title}, {c.date}
                </a>
              </blockquote>
            ))}
            <div className="small">
              <span className="muted">You: </span>
              {t.answer ?? <em className="muted">waiting for your answer…</em>}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

function ResourceList({ items }: { items: ResourceItem[] }) {
  return (
    <ul className="resources">
      {items.map((r) => (
        <li key={r.url}>
          <a href={r.url} target="_blank" rel="noreferrer">
            {r.title}
          </a>
          <div className="muted small">
            {r.publisher} · {r.date}
          </div>
        </li>
      ))}
    </ul>
  );
}

export function ResourcesCard({ r }: { r: ResourceSet | null }) {
  if (!r?.asset) return null;
  return (
    <section className="card">
      <div className="card-head">
        <h2>Resources · {r.asset}</h2>
        <span className="muted small">documents to read, not recommendations</span>
      </div>
      <div className="small muted">Vetted sources (what the devil cites)</div>
      <ResourceList items={r.vetted ?? []} />
      <div className="small muted" style={{ marginTop: 12 }}>
        Recent SEC filings mentioning {r.asset} (live from EDGAR)
      </div>
      {r.edgar_ok === false ? (
        <p className="small muted">Couldn't reach SEC EDGAR just now.</p>
      ) : r.recent_filings?.length ? (
        <ResourceList items={r.recent_filings} />
      ) : (
        <p className="small muted">None in the last four months.</p>
      )}
    </section>
  );
}
