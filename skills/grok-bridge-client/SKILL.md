---
name: grok-bridge-client
description: How a Grok Bot / Local Computer Assistant connects to the user's Grok Desktop Bridge over remote streamable-HTTP (Grok-only). Not for Claude, Codex, Cursor, or other MCP hosts.
---

# Grok Desktop Bridge — client skill (Grok Bot only)

Use this **only** when you are a **Grok Bot / Local Computer Assistant** talking to the user's Windows PC through **Grok Desktop Bridge** remote mode.

Other products (Claude Desktop, Codex, Cursor local, browser free accounts, random MCP clients) **must not** connect. The HTTP front rejects them.

## Connection

1. User runs: `python launcher.py --remote --port 8790` (instance `grok`, loopback only).
2. User starts: `cloudflared tunnel --url http://127.0.0.1:8790`.
3. User gives **you alone**:
   - URL: `https://<tunnel-host>/mcp`
   - Token from `python launcher.py --add-bot <name>`
4. Every request must include:
   - `Authorization: Bearer <token>`
   - `X-Grok-Bridge-Client: grok-bot`
5. MCP `initialize` `clientInfo.name` must be `Grok` or `Local Computer Assistant` (never Claude/Codex/Cursor).
6. Announce that you are on their Grok Desktop Bridge and they can press **Esc** on the PC to stop you.

If you get 403, you are not identified as Grok — fix headers / clientInfo; do not ask the user to weaken the gate.

## Do not

- Do not ask the user to share the tunnel URL or token with anyone else or with another AI product.
- Do not suggest wiring Claude Desktop / Codex / Cursor to this endpoint.

## Shared multi-bot rules

Several of the user's Grok bots may share one bridge. Esc stops **every** session and the HTTP front. Treat `KILL_SWITCH` as absolute.

## While you control the desktop

- White pulsing border; label: **Grok is using your computer. Press Esc to Stop**.
- Prefer visible actions. No hidden windows/processes.
- On `KILL_SWITCH` / `INJECTION_LOCKOUT` / `OVERLAY_UNAVAILABLE` / `SELF_TARGET_REFUSED`: stop, tell the user, wait. Never self-resume after injection lockout.
- Deletes → Recycle Bin; say so.
- Do not target the feed window or overlay.

## Up-front line

> I'm connected to your Grok Desktop Bridge. You'll see a white border while I use the PC — press **Esc** to cancel, Esc again to stop the bridge for every bot.
