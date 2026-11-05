---
name: grok-bridge-client
description: How any Grok Bot (or compatible MCP client) connects to a user's Grok Desktop Bridge over remote streamable-HTTP, and the safety rules it must obey.
---

# Grok Desktop Bridge — client skill (generic)

Use this when you are a **cloud** Grok Bot / Local Computer Assistant (or any MCP client) talking to a user's Windows PC through the **Grok Desktop Bridge** remote mode.

## Connection

1. The user runs the bridge locally: `python launcher.py --remote` (loopback MCP HTTP + elevated guardian).
2. The user starts an **outbound** tunnel (default: `cloudflared tunnel --url http://127.0.0.1:8765`).
3. The user gives you:
   - **URL**: `https://<tunnel-host>/mcp`
   - **Token**: a per-bot Bearer token from `python launcher.py --add-bot <your-name>`
4. Send MCP JSON-RPC over HTTP POST to that URL with header:
   `Authorization: Bearer <token>`
5. Announce in chat that you are connected to their **Grok Desktop Bridge** and that they can press **Esc** on the PC to stop you.

Do not invent another URL or skip the token. If auth fails (401), ask the user to rotate or re-issue your bot token.

## Shared multi-bot rules

- Several bots may share one bridge and one guardian feed. Your calls are tagged with your bot name in the feed and logs.
- **Esc** (and kill hotkeys) stop **every** bot's sessions and the HTTP front. Treat `KILL_SWITCH` as absolute.
- Never try to bypass the overlay, feed, injection gate, or config approval.

## While you control the desktop

- The user sees a **white pulsing** border and the label: **Grok is using your computer. Press Esc to Stop**.
- Prefer visible actions (real mouse glide, real typing). Do not hide windows or run hidden processes.
- If any tool returns `KILL_SWITCH`, `INJECTION_LOCKOUT`, `OVERLAY_UNAVAILABLE`, or `SELF_TARGET_REFUSED`: **stop**, tell the user what you were doing, and wait for their explicit instruction. Never call `desktop_resume` on your own after an injection lockout (only the user can clear that in the feed window).
- After a user kill: apologize briefly, summarize, and wait. Only resume when they clearly ask you to continue.
- Deletes go to the Recycle Bin; say so when you delete.
- Do not target the bridge's own feed window or overlay (`SELF_TARGET_REFUSED`).

## Tool surface

Same `desktop_*` tools as local stdio mode (screenshot, click, type, key, window, fs, run, …). Prefer the project's `skills/desktop-control/SKILL.md` for detailed tool etiquette when that skill is available.

## What you must say up front

On first successful tool use in a session, briefly tell the user:

> I'm connected to your Grok Desktop Bridge. You'll see a white border while I use the PC — press **Esc** to cancel, Esc again to stop the bridge for every bot.

Keep that promise: respect Esc immediately.
