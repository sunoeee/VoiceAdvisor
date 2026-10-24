import { useCallback, useEffect, useState } from "react";
import { useConversation } from "@elevenlabs/react";
import { api, type PendingTrade, type Portfolio, type TradeRecord } from "./api";
import { AgentTools } from "./AgentTools";
import { PendingCard, PortfolioCard, TradeLog, Transcript, type Line } from "./components";

const AGENT_ID = import.meta.env.VITE_ELEVENLABS_AGENT_ID as string | undefined;

export default function App() {
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [pending, setPending] = useState<PendingTrade | null>(null);
  const [history, setHistory] = useState<TradeRecord[]>([]);
  const [lines, setLines] = useState<Line[]>([]);
  const [typed, setTyped] = useState("");

  const add = (role: Line["role"], text: string) => setLines((l) => [...l, { role, text }]);

  const refresh = useCallback(async () => {
    const [p, t] = await Promise.all([api.portfolio(), api.trades()]);
    if (!p.error) setPortfolio(p);
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

  return (
    <div className="app">
      <AgentTools onChange={refresh} />
      <header>
        <div>
          <h1>Talk-to-Trade</h1>
          <div className="muted">Your portfolio, by voice.</div>
        </div>
        <button className={`talk ${connected ? "on" : ""}`} onClick={toggleTalk}>
          <span className={`dot ${connected ? (convo.isSpeaking ? "speaking" : "listening") : ""}`} />
          {connected ? (convo.isSpeaking ? "Speaking… tap to end" : "Listening… tap to end") : "Talk"}
        </button>
      </header>

      <main>
        <div className="col">
          <PortfolioCard p={portfolio} />
          <PendingCard trade={pending} onConfirm={confirmClick} onCancel={cancelClick} />
        </div>
        <div className="col">
          <Transcript lines={lines} />
          <form className="typebox" onSubmit={sendTyped}>
            <input
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              placeholder={connected ? "Or type to the agent…" : "Start a session to type"}
              disabled={!connected}
            />
          </form>
          <TradeLog history={history} />
        </div>
      </main>
      <footer className="muted small">
        Educational demo. Trades are capped and require confirmation. Not financial advice.
      </footer>
    </div>
  );
}
