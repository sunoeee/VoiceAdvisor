import { useCallback, useEffect, useState } from "react";
import { useConversation } from "@elevenlabs/react";
import { api, type DevilState, type Guidance, type Markets, type PendingTrade, type Portfolio, type ResourceSet, type TradeRecord } from "./api";
import { AgentTools } from "./AgentTools";
import { BriefCard, DevilCard, GuidanceCard, MarketCard, PendingCard, PortfolioCard, ResourcesCard, TradeLog, Transcript, type Line } from "./components";

const AGENT_ID = import.meta.env.VITE_ELEVENLABS_AGENT_ID as string | undefined;

export default function App() {
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [markets, setMarkets] = useState<Markets | null>(null);
  const [pending, setPending] = useState<PendingTrade | null>(null);
  const [history, setHistory] = useState<TradeRecord[]>([]);
  const [lines, setLines] = useState<Line[]>([]);
  const [typed, setTyped] = useState("");
  const [devil, setDevil] = useState<DevilState | null>(null);
  const [resources, setResources] = useState<ResourceSet | null>(null);
  const [guidance, setGuidance] = useState<Guidance | null>(null);
  const [brief, setBrief] = useState<{ text: string | null; source: string | null; audio: string | null; status: string | null }>({
    text: null,
    source: null,
    audio: null,
    status: null,
  });

  // Morning brief: Qwen writes it from live True Markets data, ElevenLabs reads it aloud.
  async function getBrief() {
    setBrief({ text: null, source: null, audio: null, status: "writing" });
    const r = await api.summary();
    if (!r.say) {
      setBrief({ text: null, source: null, audio: null, status: `error:${r.error ?? "Couldn't load the brief."}` });
      return;
    }
    setBrief({ text: r.say, source: r.source, audio: null, status: "voicing" });
    const v = await api.speak(r.say);
    setBrief({ text: r.say, source: r.source, audio: v.url ?? null, status: v.error ? `error:${v.error}` : null });
  }

  const add = (role: Line["role"], text: string) => setLines((l) => [...l, { role, text }]);

  const refresh = useCallback(async () => {
    const [p, t, m, d, res] = await Promise.all([
      api.portfolio(),
      api.trades(),
      api.markets(),
      api.devil(),
      api.lastResources(),
    ]);
    if (!d.error) setDevil(d);
    if (!res.error) setResources(res);
    if (!p.error) setPortfolio(p);
    setMarkets(m);
    if (!t.error) {
      setPending(t.pending[0] ?? null);
      setHistory(t.history);
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 5000);
    return () => clearInterval(id);
  }, [refresh]);

  const convo = useConversation({
    onMessage: ({ message, role }) => add(role === "user" ? "user" : "agent", message),
    onError: (message) => add("system", `Voice error: ${message}`),
    onDisconnect: () => add("system", "Voice session ended."),
  });
  const connected = convo.status === "connected";

  async function toggleTalk() {
    if (connected) return convo.endSession();
    if (!AGENT_ID) return add("system", "Set VITE_ELEVENLABS_AGENT_ID in frontend/.env.local first.");
    try {
      await navigator.mediaDevices.getUserMedia({ audio: true });
      convo.startSession({ agentId: AGENT_ID, connectionType: "webrtc" });
    } catch {
      add("system", "Microphone permission is needed to talk.");
    }
  }

  // On-screen backup for the voice confirmation (noisy venue, flaky mic).
  async function confirmClick() {
    const r = await api.execute(pending?.confirmation_id);
    add("system", r.say ?? "Trade sent.");
    if (connected && r.say) convo.sendContextualUpdate(`The user confirmed on screen. Result: ${r.say}`);
    refresh();
  }
  async function cancelClick() {
    const r = await api.cancel(pending?.confirmation_id);
    add("system", r.say ?? "Cancelled.");
    refresh();
  }

  function sendTyped(e: React.FormEvent) {
    e.preventDefault();
    if (!typed.trim() || !connected) return;
    convo.sendUserMessage(typed.trim());
    add("user", typed.trim());
    setTyped("");
  }

  const lastAgent = [...lines].reverse().find((l) => l.role === "agent")?.text;
  const lastUser = [...lines].reverse().find((l) => l.role === "user")?.text;
  const voiceState = !connected ? "off" : convo.isSpeaking ? "speaking" : "listening";
  const liveTrading = portfolio && portfolio.broker !== "mock";
  const devilActive = !!devil?.active;
  const resourcesActive = !!resources?.asset;

  return (
    <div className="app">
      <AgentTools onChange={refresh} onGuidance={setGuidance} />
      <header className="topbar">
        <div className="brand">
          <span className="logo">T</span>
          <div>
            <h1>Ticker</h1>
            <div className="muted small">Talk-to-Trade · voice crypto trading on True Markets</div>
          </div>
        </div>
        <div className="pills">
          <span className={`pill ${liveTrading ? "ok" : "warn"}`}>{liveTrading ? "Live trading" : "Practice mode"}</span>
          <span className={`pill ${voiceState === "off" ? "" : "ok"}`}>Voice {voiceState === "off" ? "off" : "on"}</span>
        </div>
      </header>

      <section className={`stage ${voiceState}`}>
        <button className="orb" onClick={toggleTalk} aria-label={connected ? "End voice session" : "Start talking to Ticker"}>
          <span className="ring r1" />
          <span className="ring r2" />
          <span className="orb-core">{voiceState === "off" ? "Talk" : voiceState === "speaking" ? "Speaking" : "Listening"}</span>
        </button>
        <div className="caption">
          {lastAgent ? (
            <>
              {lastUser && <div className="you">“{lastUser}”</div>}
              <div className="said">{lastAgent}</div>
            </>
          ) : (
            <div className="said muted">Press Talk and just ask. No mouse needed after that.</div>
          )}
        </div>
        <div className="chips" aria-label="Things you can say">
          {[
            "Good morning, Ticker",
            "I'm thinking of putting 30% into NVIDIA. Thoughts?",
            "What's SOL at?",
            "Buy one dollar of SOL",
            "Give me a second opinion on SOL",
            "What should I read about SOL?",
          ].map((c) => (
            <span key={c} className="chip">“{c}”</span>
          ))}
        </div>
      </section>

      <main className="grid">
        <div className="col">
          <BriefCard text={brief.text} source={brief.source} audioUrl={brief.audio} status={brief.status} onGet={getBrief} />
          <PortfolioCard p={portfolio} />
          <MarketCard markets={markets} liveTrading={!!liveTrading} />
        </div>
        <div className="col focus">
          <PendingCard trade={pending} onConfirm={confirmClick} onCancel={cancelClick} />
          {devilActive && <DevilCard d={devil} onReset={() => api.devilReset().then(refresh)} />}
          {resourcesActive && <ResourcesCard r={resources} />}
          <GuidanceCard g={guidance} onClose={() => setGuidance(null)} />
          {!pending && !devilActive && !resourcesActive && !guidance && (
            <section className="card idle">
              <h2>Right now</h2>
              <p className="muted">
                Quotes waiting for “confirm”, devil’s-advocate questions and reading lists show up here as you talk.
              </p>
              <p className="muted small">
                Ask for a second opinion and Ticker challenges your reasoning with SEC filings and press releases. It never tells you
                to buy or sell.
              </p>
            </section>
          )}
        </div>
        <div className="col">
          <Transcript lines={lines} />
          <form className="typebox" onSubmit={sendTyped}>
            <input
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              placeholder={connected ? "Or type to Ticker…" : "Start a voice session to type"}
              disabled={!connected}
            />
          </form>
          <TradeLog history={history} />
        </div>
      </main>
      <footer className="muted small">
        Educational demo. Trades are capped at $10, need your spoken “confirm”, and run on True Markets. Not financial advice.
      </footer>
    </div>
  );
}
