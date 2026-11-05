# Remote mode quickstart (Windows)

Opt-in: serve the **same** Grok Desktop Bridge tool set over MCP streamable-HTTP on **127.0.0.1 only**, with a **per-bot Bearer token**. You expose that localhost port with an **outbound** tunnel you control. All safety stays on the PC: visible action feed, white pulsing overlay, two-stage Esc kill switch (stops **every** bot + the HTTP server), injection gate, config approval.

## 1. Install deps (PowerShell)

```powershell
cd $env:USERPROFILE\grok-desktop-bridge   # or your clone path
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Install [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/) (or another outbound tunnel) and ensure it is on `PATH`.

## 2. Create a named bot token

Each cloud Grok Bot gets its **own** token. Do this once per bot:

```powershell
.\.venv\Scripts\python.exe launcher.py --add-bot work
```

Copy the printed `token:` line. Store it only for that bot.

Other commands:

```powershell
.\.venv\Scripts\python.exe launcher.py --list-bots
.\.venv\Scripts\python.exe launcher.py --revoke-bot work
```

Tokens live in `%LOCALAPPDATA%\GrokDesktopBridge\remote_bots.json` (user-readable; treat like a password).

## 3. Start the launcher in remote mode

```powershell
.\.venv\Scripts\python.exe launcher.py --remote --port 8765
```

- Binds `http://127.0.0.1:8765/mcp` only (loopback).
- Starts / joins the elevated guardian (UAC / scheduled task as usual). Allow the client in the feed window the first time.
- Prints bot token prefixes and the tunnel hint.
- First request for a bot shows **Remote session connected** in the guardian feed; every remote call is logged with `[botname]`.

Leave this window open. Closing it or pressing **Esc twice** in the guardian feed stops the bridge for **all** bots.

## 4. Start the outbound tunnel

In a second PowerShell:

```powershell
cloudflared tunnel --url http://127.0.0.1:8765
```

Cloudflared prints a public `https://….trycloudflare.com` URL. That is the only URL you hand out.

## 5. What to give the cloud bot

| Item | Value |
|------|--------|
| MCP URL | `https://<cloudflared-host>/mcp` |
| Header | `Authorization: Bearer <token from --add-bot>` |
| Transport | MCP streamable HTTP (JSON-RPC POST to `/mcp`) |

Point the bot (or Cursor custom MCP connector) at that URL + header. See `skills/grok-bridge-client/SKILL.md` for the rules every bot must follow.

## Safety (unchanged in remote mode)

- Visible guardian **action feed** (black/white console).
- **White** border that pulses grey↔white + label: `Grok is using your computer. Press Esc to Stop`.
- **Esc** cancels in-flight calls; Esc again stops the guardian, every bot session, and the HTTP server.
- Injection gate, config approval, no hidden execution, Recycle Bin deletes — same as local stdio.

## Notes

- Multiple bots: create multiple `--add-bot` names; they share one `--remote` listener and one guardian. Esc stops all of them.
- Do **not** bind to a public interface; the launcher refuses non-loopback hosts.
- Prefer revoking a token (`--revoke-bot`) over leaving an old tunnel URL active.
