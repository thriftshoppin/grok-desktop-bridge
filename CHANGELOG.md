# Changelog

## Unreleased

- **Grok-only remote + isolation:** remote HTTP requires `X-Grok-Bridge-Client`; rejects Claude/Codex/Cursor UA/`clientInfo`. Defaults: instance `grok`, port **8790**, `GrokDesktopBridge` paths/pipes/mutex/task; Claude log paths removed from `config.json`. Docs warn never to share tunnel URL+token.
- **White pulsing overlay:** border pulses smoothly grey↔white; label is exactly `Grok is using your computer. Press Esc to Stop`. Halo is white. Feed accents use a high-contrast black/white palette. Config default `overlay.color` is `#FFFFFF`.
- **Remote mode (opt-in):** `launcher.py --remote` serves the same MCP tool set over streamable-HTTP on `127.0.0.1` with Bearer auth. Esc / feed close stops the HTTP server and every session. Documented tunnel: `cloudflared tunnel --url http://127.0.0.1:<port>`. See `docs/REMOTE_QUICKSTART.md`.
- **Multi-bot tokens:** `--add-bot` / `--list-bots` / `--revoke-bot`; each remote call tagged with the bot name in the feed and logs; shared guardian and kill switch. Generic client skill: `skills/grok-bridge-client/SKILL.md`.
- **Tests:** `tests/test_remote_auth.py` (token reject / multi-bot store; runs on Linux).

Work in progress; no release has been tagged yet. Dates are 2026.

## Unreleased
- **Grok rebrand (fork):** user-facing strings, feed window title, overlay label, and docs now describe this as the Grok Desktop Bridge / Local Computer Assistant bridge. Claude desktop client detection and primary priority remain for compatibility. Safety behaviour unchanged. Overlay theme is white pulsing (grey↔white); remote multi-bot HTTP mode added.
- **Control pipe hardening (audit DB-1, DB-2):** the launcher authenticates the owner of the control pipe (image and High integrity) before sending anything; the guardian reports a squatted control pipe loudly and stops; silent control connections time out after 5 s; connections are capped per process (4) and in total (32 unanswered).
- Docs: architecture, configuration, operations, testing, generated tool reference, security audit log, threat model and disclaimer.

## 2026-10-30 - shared guardian
- One persistent elevated guardian per Windows session shared by every MCP client; launchers are thin relays; Claude desktop is the primary client (input priority).
- One-time typed "Allow client?" allow-list, kernel-verified client pid, per-session pipe pair and one-time token, identity walk from launcher to the starting program.
- Two-stage Esc: first press cancels every in-flight call of every client, second press (within 10 s) stops the bridge.
- Prompts: typed in the visible feed console, stale typed-ahead keys discarded, withdrawn when the asker has gone; guardian refuses to run without a visible console.
- Approval store moved to `%ProgramData%\DesktopBridge\state` (a packaged app's `%LOCALAPPDATA%` is redirected).

## Earlier (M0 - M0.3)
- Takeover core: screenshot/zoom, UI Automation tree and find, real mouse and visible typing, shortcuts, launch, run, fs (Recycle Bin deletes), clipboard, audio level.
- Visibility: white pulsing border on every monitor while in control, everything runs in the visible feed console, no hidden execution.
- Safety layer: hash-chained action log, kill switch hotkeys, process denylist, protected paths, injection gate with user-only lockout clearing, config approval, awareness guards (target closed, focus changed, user intervention), multi-monitor coordinate mapping.
