# Remote mode quickstart (Windows) — Grok Bot cloud only

Opt-in: serve the **same** Grok Desktop Bridge tool set over MCP streamable-HTTP on **127.0.0.1 only**, with a **per-bot Bearer token** and a required **`X-Grok-Bridge-Client`** header. You expose that localhost port with an **outbound** tunnel you control.

**This remote path is for your Grok Bot / Local Computer Assistant (cloud) only.** It is not a public MCP endpoint. Claude Desktop, Codex, Cursor local, browser “free accounts”, and other MCP hosts are **rejected** (missing Grok client header, blocked User-Agent / `clientInfo`).

## Do not

- **Never share the tunnel URL + token** with other people, free/browser accounts, or other AI products. That is handing over control of your PC.
- Do not post the URL in Discord, chat, email, or tickets.
- Do not add Claude Desktop / Codex / Cursor as MCP clients pointed at this tunnel.
- Do not bind to a public interface (the launcher refuses non-loopback hosts).

## Isolation from Claude / Codex bridge

This install does **not** share pipes, mutexes, AppData, or the scheduled task with `desktop-mcp-bridge`:

| Setting | Grok Desktop Bridge (this repo) |
|---------|----------------------------------|
| Instance | `grok` (`DESKTOP_BRIDGE_INSTANCE`, default) |
| Remote port | **8790** |
| Pipes / mutexes | `grok-desktop-bridge-*` / `GrokDesktopBridge*` |
| State / tokens | `%ProgramData%\GrokDesktopBridge`, `%LOCALAPPDATA%\GrokDesktopBridge` |
| Temp / feed logs | `%TEMP%\GrokDesktopBridge` |
| Scheduled task | `GrokDesktopBridgeWorker` |

Both bridges can run on the same PC.

## 0. From scratch

Unzip this source and double-click `Install-GrokBridge.cmd`. That removes only the Grok targets it prints (after you confirm) and installs to `%USERPROFILE%\grok-desktop-bridge`. Then double-click the desktop shortcut **Grok Desktop Bridge Light Switch**. See the README. Do not use an in-place patch script.

## 1. Install deps (PowerShell)

```powershell
cd $env:USERPROFILE\grok-desktop-bridge   # or your clone path
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Install [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/) and ensure it is on `PATH`.

## 2. Create a named bot token

```powershell
$env:DESKTOP_BRIDGE_INSTANCE = "grok"   # default anyway; set explicitly if you like
.\.venv\Scripts\python.exe launcher.py --add-bot work
```

Copy the printed `token:` line. One token per cloud bot. Revoke with `--revoke-bot work`.

## 3. Start remote mode (port 8790)

```powershell
$env:DESKTOP_BRIDGE_INSTANCE = "grok"
.\.venv\Scripts\python.exe launcher.py --remote --port 8790
```

- Binds `http://127.0.0.1:8790/mcp` only.
- Starts / joins the elevated **Grok** guardian (UAC / `GrokDesktopBridgeWorker` task). Allow the client in the feed once.
- Every request needs `Authorization: Bearer <token>` **and** `X-Grok-Bridge-Client: grok-bot`.

Leave this window open. **Esc twice** in the guardian feed stops the bridge for **all** bots and the HTTP server.

## 4. Outbound tunnel

```powershell
cloudflared tunnel --url http://127.0.0.1:8790
```

Use only the printed `https://….trycloudflare.com` URL with **your** Grok Bot.

## 5. What to give your Grok Bot (only)

| Item | Value |
|------|--------|
| MCP URL | `https://<cloudflared-host>/mcp` |
| Header | `Authorization: Bearer <token>` |
| Header | `X-Grok-Bridge-Client: grok-bot` |
| Transport | MCP streamable HTTP (JSON-RPC POST to `/mcp`) |
| `clientInfo.name` | `Grok` or `Local Computer Assistant` (not Claude/Codex/Cursor) |

See `skills/grok-bridge-client/SKILL.md`. Production use is **remote Grok only**; local stdio remains for selftest on this PC.

## Safety (unchanged)

Visible action feed, white pulsing border + `Grok is using your computer. Press Esc to Stop`, two-stage Esc, injection gate, config approval, Recycle Bin deletes, client allow-list — all still on the PC.
