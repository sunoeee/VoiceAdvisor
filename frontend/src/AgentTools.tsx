import { useConversationClientTool } from "@elevenlabs/react";
import { api } from "./api";

/**
 * Client tools the ElevenLabs agent can call.
 *
 * Names and parameters MUST match the tools configured on the agent in the
 * ElevenLabs dashboard (see agent/tools.md), and each tool must have
 * "Wait for response" turned on so the agent reads the result back.
 *
 * Each tool returns a JSON string; the `say` field is the sentence the agent
 * should speak. Safety rules live on the backend, not here.
 */
type Params = Record<string, unknown>;

const json = (x: unknown) => JSON.stringify(x);
const str = (v: unknown) => (typeof v === "string" ? v : v == null ? "" : String(v));

export function AgentTools({ onChange }: { onChange: () => void }) {
  useConversationClientTool("get_portfolio_summary", async () => {
    const r = await api.summary();
    onChange();
    return json({ say: r.say, total_usd: r.portfolio?.total_usd, error: r.error });
  });

  useConversationClientTool("get_portfolio_insights", async () => {
    const r = await api.insights();
    return json({ say: r.say, error: r.error });
  });

  useConversationClientTool("get_price", async (p: Params) => {
    return json(await api.price(str(p.asset)));
  });

  useConversationClientTool("prepare_trade", async (p: Params) => {
    const r = await api.prepare(str(p.asset), str(p.side), Number(p.usd_amount));
    onChange();
    return json(r);
  });

  useConversationClientTool("confirm_trade", async (p: Params) => {
    const r = await api.execute(str(p.confirmation_id) || undefined);
    onChange();
    return json(r);
  });

  useConversationClientTool("cancel_trade", async (p: Params) => {
    const r = await api.cancel(str(p.confirmation_id) || undefined);
    onChange();
    return json(r);
  });

  useConversationClientTool("challenge_thesis", async (p: Params) => {
    const r = await api.challenge(str(p.asset), str(p.user_text), p.restart === true || p.restart === "true");
    onChange();
    return json(r);
  });

  useConversationClientTool("find_resources", async (p: Params) => {
    const r = await api.resources(str(p.asset));
    onChange();
    return json({ say: r.say, error: r.error });
  });

  return null;
}
