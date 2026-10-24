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
  price_source?: string;
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

export type DevilCitation = { source_id: string; excerpt_id: string; quote: string; title: string; url: string; date: string };
export type DevilState = {
  active: boolean;
  asset?: string;
  thesis?: string;
  rounds?: number;
  turns?: { question: string; answer: string | null; source: "llm" | "fallback"; citations: DevilCitation[] }[];
};

export type ResourceItem = { title: string; publisher: string; date: string; url: string; kind: string };
export type ResourceSet = { asset: string | null; vetted?: ResourceItem[]; recent_filings?: ResourceItem[]; edgar_ok?: boolean };

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

export type Guidance = {
  analysis: {
    question: string;
    asset?: { symbol: string; name: string; type: string } | null;
    amount_usd?: number;
    amount_pct_of_portfolio?: number;
    asset_weight_after_pct?: number;
    facts: string[];
    suggested_questions: string[];
  };
  source: string;
};

export type MarketPrice = { asset: string; price_usd: number; source: string; say?: string };

export type Markets = {
  source: string;
  prices: MarketPrice[];
  unavailable?: { asset: string; error: string }[];
};

export const api = {
  health: () => call<{ ok: boolean; broker: string; market: string; max_trade_usd: number; allowed_assets: string[] }>("/health"),
  markets: () => call<Markets>("/markets"),
  advise: (question: string, asset?: string, usd_amount?: number, percent_of_portfolio?: number) =>
    post<Guidance>("/advise", { question, asset, usd_amount, percent_of_portfolio }),
  portfolio: () => call<Portfolio>("/portfolio"),
  summary: () => call<{ portfolio: Portfolio; source: string }>("/summary"),
  /** ElevenLabs reads `text` aloud; resolves to an object URL for an <audio> element, or an error. */
  speak: async (text: string): Promise<{ url?: string; error?: string }> => {
    const res = await fetch("/api/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      return { error: body.error ?? `Text-to-speech failed (${res.status}).` };
    }
    return { url: URL.createObjectURL(await res.blob()) };
  },
  insights: () => call<{ source: string }>("/insights"),
  price: (asset: string) => call<{ asset: string; price_usd: number }>(`/price/${encodeURIComponent(asset)}`),
  prepare: (asset: string, side: string, usd: number) => post<PendingTrade>("/trades/prepare", { asset, side, usd }),
  execute: (confirmation_id?: string) => post<TradeRecord>("/trades/execute", { confirmation_id }),
  cancel: (confirmation_id?: string) => post<object>("/trades/cancel", { confirmation_id }),
  challenge: (asset: string, text: string, restart = false) =>
    post<{ round?: number; done: boolean; question?: string }>("/devil/challenge", { asset, text, restart }),
  devil: () => call<DevilState>("/devil"),
  devilReset: () => post<object>("/devil/reset", {}),
  resources: (asset: string) => call<ResourceSet>(`/resources/${encodeURIComponent(asset)}`),
  lastResources: () => call<ResourceSet>("/resources"),
  trades: () => call<{ pending: PendingTrade[]; history: TradeRecord[] }>("/trades"),
};
