// Thin client for the FastAPI backend (proxied at /api by Vite).

export type Position = {
  symbol: string;
  qty: number;
  price_usd: number;
  value_usd: number;
  weight_pct: number;
};

export type Portfolio = {
  total_usd: number;
  cash_usd: number;
  positions: Position[];
  broker: string;
};

export type PendingTrade = {
  confirmation_id: string;
  asset: string;
  side: "buy" | "sell";
  usd: number;
  est_qty: number;
  price_usd: number;
  expires_in_seconds: number;
};

export type TradeRecord = {
  order_id: string;
  status: string;
  asset: string;
  side: "buy" | "sell";
  usd: number;
  base_qty: number;
  price: number;
  at: number;
};

/** Every response may carry `say`: a sentence the agent should read aloud. */
export type Spoken = { say?: string; error?: string };

async function call<T>(path: string, init?: RequestInit): Promise<T & Spoken> {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  let body: (T & Spoken) | null = null;
  try {
    body = await res.json();
  } catch {
    /* non-JSON error */
  }
  if (!res.ok) {
    const say = body?.say ?? `The server returned an error (${res.status}).`;
    return { ...(body ?? ({} as T)), error: body?.error ?? say, say };
  }
  return body as T & Spoken;
}

const post = <T,>(path: string, data: unknown) =>
  call<T>(path, { method: "POST", body: JSON.stringify(data) });

export type MarketPrice = { asset: string; price_usd: number; source: string; say?: string };

export type Markets = {
  source: string;
  prices: MarketPrice[];
  unavailable?: { asset: string; error: string }[];
};

export const api = {
  health: () => call<{ ok: boolean; broker: string; market: string; max_trade_usd: number; allowed_assets: string[] }>("/health"),
  markets: () => call<Markets>("/markets"),
  portfolio: () => call<Portfolio>("/portfolio"),
  summary: () => call<{ portfolio: Portfolio; source: string }>("/summary"),
  insights: () => call<{ source: string }>("/insights"),
  price: (asset: string) => call<{ asset: string; price_usd: number }>(`/price/${encodeURIComponent(asset)}`),
  prepare: (asset: string, side: string, usd: number) => post<PendingTrade>("/trades/prepare", { asset, side, usd }),
  execute: (confirmation_id?: string) => post<TradeRecord>("/trades/execute", { confirmation_id }),
  cancel: (confirmation_id?: string) => post<object>("/trades/cancel", { confirmation_id }),
  trades: () => call<{ pending: PendingTrade[]; history: TradeRecord[] }>("/trades"),
};
