# ElevenLabs agent: client tools

In the ElevenLabs dashboard → your agent → **Tools** → **Add tool** → type
**Client**. Create these eight. For every one:

- The name must match exactly (the frontend registers these names in
  `frontend/src/AgentTools.tsx`).
- Turn on **Wait for response** (blocking), so the agent reads the result
  before speaking.

| Tool name | Description (paste into the dashboard) | Parameters |
| --- | --- | --- |
| `get_portfolio_summary` | Gets a short spoken briefing of the user's portfolio: total value, biggest holding and cash available. Read the `say` field aloud. | none |
| `get_portfolio_insights` | Gets two or three educational observations about the portfolio's diversification and cash level. Read the `say` field aloud. | none |
| `get_price` | Gets the current US dollar price of one asset. | `asset` (string, required): symbol such as BTC, ETH or SOL |
| `prepare_trade` | Prepares a buy or sell and returns a quote that must be read back to the user. Does NOT place the trade. | `asset` (string, required): BTC, ETH or SOL · `side` (string, required): "buy" or "sell" · `usd_amount` (number, required): dollars to spend or receive |
| `confirm_trade` | Places the trade the user just confirmed out loud. Only call right after the user says confirm. | `confirmation_id` (string, required): the id returned by prepare_trade |
| `challenge_thesis` | Use ONLY when the user explicitly asks for a second opinion or devil's advocate. Plays devil's advocate on the user's reason for liking an asset. Returns one pointed, source-backed question at a time; read the `say` field aloud. Call again with the user's answer until `done` is true. Never places or blocks a trade. | `asset` (string, required): BTC, ETH or SOL · `user_text` (string, required): the user's thesis on the first call, their answer after that · `restart` (boolean, optional): true to start over with a new thesis |
| `find_resources` | Gathers documents to read about an asset: the vetted sources the devil cites plus recent SEC filings that mention it, shown on screen. Read the `say` field aloud. | `asset` (string, required): BTC, ETH or SOL |
| `cancel_trade` | Cancels the trade that is waiting for confirmation. | `confirmation_id` (string, optional) |

## Other agent settings

- **First message**: see the last line of `system_prompt.md`.
- **Voice**: pick a clear, mid-tempo voice; test it over the venue speakers.
- **Authentication**: leave the agent public for the demo, so the browser only
  needs the agent ID. Never put the ElevenLabs API key in the frontend.
- **LLM**: the dashboard default is fine for conversation. Portfolio analysis
  comes from our open-source model through the backend.

## Stretch: run the whole agent brain on the open model

ElevenLabs agents can point at a custom, OpenAI-compatible LLM endpoint. If you
host the open model somewhere public (for example on DigitalOcean), you can set
it as the agent's LLM. Check the current ElevenLabs docs for the exact setting
before trying this; it isn't needed for the core demo.
