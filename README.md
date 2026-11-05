> **Work in progress.** Fork of [desktop-mcp-bridge](https://github.com/thriftshoppin/desktop-mcp-bridge) rebranded as the **Grok Desktop Bridge** for Grok / Local Computer Assistant. Early personal build for one Windows PC. M0 (the "takeover core") is written and mostly tested; M1-M3 are not started. **Remote mode (opt-in streamable-HTTP + outbound tunnel) is implemented** — see [Remote mode](#remote-mode-implemented--grok-bot-cloud-only) and `docs/REMOTE_QUICKSTART.md`.
> Not production-ready and not hardened for public use: it runs an **elevated** worker that can see the screen and control the keyboard and mouse, and its safety checks are best-effort. Read SECURITY.md before running anything. Paths in `config.json` are specific to the original author's machine — edit them for yours.

# Grok Desktop Bridge

**Disclaimer.** Grok Desktop Bridge gives an AI agent control of your computer. It is experimental. It assumes the machine is not already compromised and cannot verify that. Use it at your own risk, on a machine you trust, and keep the kill switch (Esc) in reach.

One local stdio MCP server that lets **Grok / Local Computer Assistant** (and, for compatibility, Claude desktop / Claude Code) use **this Windows PC** the way a person does: see the screen, read the UI tree,
click, type, press shortcuts, open apps, move files, run commands, and check whether audio is playing. Personal tool. The guardian still has **no inbound network listener** today. Paths live in `config.json`.

**Everything is visible.** The worker runs in a normal console window ("Grok Desktop Bridge - live action feed") that prints every tool
call, every command it runs and its output, and every kill-switch event. Nothing is hidden: no `pythonw`, no `SW_HIDE`, no
`CREATE_NO_WINDOW`; helper processes share that console. Every call is also written to the actions log.

## How it is built

```
Grok / Local Computer Assistant = PRIMARY (intended)   Claude desktop / Claude Code = optional / legacy
        | stdio MCP (today) / remote relay (planned)            | stdio MCP
   launcher.py (Medium, stdlib only, thin relay)           launcher.py (same file, same relay)
        \_______ control pipe: user-only DACL, kernel-verified client PID ______/
                                      v
            THE GUARDIAN: one elevated worker per Windows session, one visible feed window  -- MCP server (mcp 2.3.0 `MCPServer`)
              per-client sessions (own pipe pair + one-time token, own screenshot/element references)
              ONE shared UI thread (input of all clients is serialized; the primary client goes first), overlay, two-stage Esc, hotkeys,
              capture (DXGI, GDI fallback) - UI Automation - SendInput - clipboard - audio probe - queued action log
```

* **One shared bridge, like a primary/relay setup:** the first launcher that finds no guardian starts it (silent `runas`, one visible window); every
  later launcher, from any client, joins it. No extra feed windows or config prompts per client or session.
* **Grok / Local Computer Assistant is the intended primary client** (Claude desktop remains primary too for compatibility): its input goes first when two clients want the mouse or keyboard
  at the same moment; other clients wait briefly (they are never refused for that). Every log line and `session_status` names the client.
* **A client the guardian has never seen is not served until you allow it, once:** the feed window asks `Allow client '...' ... (y/N)`;
  the answer is remembered (state folder `%ProgramData%\DesktopBridge\state`, outside the packaged-app file redirection).
* The guardian exits by itself after `guardian.idle_exit_min` (default 120) minutes without a client, or when you close its window. If `runas`
  fails, the launcher falls back to the scheduled task `DesktopBridgeWorker` (create it once with `install-elevated-task.ps1`).
* UAC on this PC is **enabled with silent elevation** (`ConsentPromptBehaviorAdmin=0`). The guardian is elevated, so input works in elevated windows and
  `desktop_run`/`desktop_launch` run elevated (the `elevated` parameters are kept for compatibility).

## Threat model (short)

**In scope** (the bridge tries to defend against these):
1. A prompt-injected or misused Grok / agent trying to exceed its permissions through the bridge's tools.
2. A local program that races or squats the bridge's endpoints (the control pipe, the per-session pipes).
3. A second agent client with a forged identity or header.
4. Accidental leakage: the bridge has no network listener, downloads are gated, typed text is not logged by default, captures are temporary.

**Out of scope** (accepted and documented): a host that is already compromised by malware running as the user or as an administrator. With silent UAC elevation any same-account code can become administrator, so the bridge cannot defend against it, and the maintainer cannot verify that a host is clean. Hardening that raises the cost for such malware is *defense in depth*, never a boundary.

Details: [SECURITY.md](SECURITY.md) and [docs/SECURITY-AUDIT.md](docs/SECURITY-AUDIT.md).

## Documentation
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · [docs/CONFIG.md](docs/CONFIG.md) · [docs/OPERATIONS.md](docs/OPERATIONS.md) · [docs/TESTING.md](docs/TESTING.md) · [docs/TOOLS.md](docs/TOOLS.md) (generated) · [docs/features/](docs/features/) · [CHANGELOG.md](CHANGELOG.md)

## Fresh install from scratch (Windows)

Double-click **`Install-GrokBridge.cmd`** in this folder (or the copy you unzipped). The window stays open, prints every step, and writes a log under `%USERPROFILE%\GrokDesktopBridge-logs`.

It shows the exact removal list first (Desktop and Downloads via Known Folders, including OneDrive redirection, plus `%LOCALAPPDATA%\GrokDesktopBridge`, `%ProgramData%\GrokDesktopBridge`, `%TEMP%\GrokDesktopBridge`, and the task `GrokDesktopBridgeWorker`). Nothing is deleted until you type `REMOVE LISTED GROK INSTALLS`. Reparse points are not entered. A `desktop-mcp-bridge` folder that is Claude/Codex is listed and **not** removed unless you pass `-IncludeOtherClientPath` for that exact path and type the longer phrase. The running installer directory is kept.

The fresh copy is **`%USERPROFILE%\grok-desktop-bridge`** (not a nested `-main` folder), with its own `.venv`. Supported Python is **64-bit CPython 3.12, 3.13, or 3.14**. `dxcam==0.3.0` has no 32-bit wheel and no Python 3.15 wheel; pip is run with `--only-binary=:all:` and a failed import stops the install with the pip exit code. A desktop shortcut **Grok Desktop Bridge Light Switch** is created on the Known Folder desktop.

Turn it on with that shortcut (guardian feed, `http://127.0.0.1:8790/mcp`, cloudflared). The switch prints the tunnel URL and log paths and does **not** print the bearer token. Create a token in a window you are watching:

```bat
%USERPROFILE%\grok-desktop-bridge\.venv\Scripts\python.exe %USERPROFILE%\grok-desktop-bridge\launcher.py --add-bot work
```

Preview the removal list without changing anything: `powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-GrokBridge.ps1 -DryRun`

## Install / register (you do this; the bridge never edits your client's config)

**Intended primary: Grok / Local Computer Assistant** (see [Remote mode](#remote-mode-implemented--grok-bot-cloud-only); multi-bot named tokens supported).
**Works today unchanged:** Claude desktop (Cowork) or Claude Code as a local stdio MCP client (below).

1. **Recommended first:** run `C:\Users\SysAdmin\Claude\log-tools\Protect-ClaudeLog.ps1` yourself so the actions log becomes
   append-only and audited. The bridge writes through `Add-ClaudeLog.ps1`, which only needs AppendData rights.
2. Add this to `%LOCALAPPDATA%\Claude-Data\claude_pzs8sxrjxfjjc\claude_desktop_config.json` under `mcpServers`
   (same file and shape as the existing `firefox` entry), then restart Claude desktop:

```json
"desktop": {
  "command": "C:/Users/SysAdmin/tools/claude-desktop-bridge/.venv/Scripts/python.exe",
  "args": ["C:/Users/SysAdmin/tools/claude-desktop-bridge/launcher.py"]
}
```

   (Alternatively use the repo as a Claude plugin: `.claude-plugin/plugin.json` points at the same launcher.)
3. On first use a console window titled **Grok Desktop Bridge - live action feed** appears. Leave it open; closing it stops the bridge for every client.
4. Optional fallback if `runas` is ever refused: from an elevated PowerShell run `install-elevated-task.ps1` once.
5. **Optional second client: Claude Code.** Register the same launcher in Claude Code's own MCP config (user scope), for example
   `claude mcp add --scope user desktop -- <repo>/.venv/Scripts/python.exe <repo>/launcher.py`. It joins the same guardian (no new window); the first time, the feed
   window asks once to allow it, and from then on its tool calls show up named `client=Claude Code (VS Code)`.

Rebuild the environment: `python -m venv .venv` (Python 3.14.8 here) then `.venv\Scripts\python.exe -m pip install -r requirements.txt`.

## Kill switch

**Esc is two-stage and applies to every client at once:** the first Esc **cancels every tool call that is running** (they return `CANCELLED_BY_USER`, the border turns yellow, the bridge stays usable); a **second Esc within 10 s** (`kill_switch.esc_second_press_s`), or an Esc while Grok is in control with nothing running, **stops the bridge** for everyone (border red, every call refused until you resume in the feed window).

**Esc** (global while Grok is in control, including when another app is in front), `Ctrl+Alt+Pause` or `Ctrl+Alt+Shift+K` (combos configurable in `config.json`). The worker registers the combos itself, so they work even if the
launcher or the agent hangs. (Hotkey plus a key-state poll, so it also works when no window has the foreground.) Esc is polled, not registered, so the key still reaches the foreground app. Alt/Ctrl/Win chords and a short arm/release grace ignore the synthetic Esc that Alt+Tab and the overlay can produce. On a real stop: in-flight waits, typing, clicks and `desktop_run` stop within about a second, every tool
returns `KILL_SWITCH` until someone calls `desktop_resume`, and the feed window shows it in red. `desktop_session_status` reports the state.

## Tools (prefix `desktop_`)

| Tool | What it does |
|---|---|
| `session_status` | console/rdp, locked, kill switch, log-writer health, worker elevation, foreground window |
| `monitors_list` | id, rect (physical px, may be negative), dpi, scale %, refresh |
| `screenshot(monitor?, region?, window?, format?)` | capped at 1568 px long edge; returns scale + origin; `SESSION_LOCKED` instead of a black image |
| `zoom(region, coords='shot'|'screen', upscale?)` | native-resolution crop, small crops upscaled up to 3x |
| `windows_list`, `window_focus` | top-level windows (z-order), `non_target` marks Progman/Lively/taskbar |
| `ui_tree(window?|point?, depth, filter, max_nodes)`, `find(query, window?, role?)` | UIA refs; default 800 nodes, `truncated` flag; passwords redacted |
| `click(ref | x,y, button, count, modifiers, coords)`, `type(text, ref?, method='keys'|'value', clear?)`, `key(combo, repeat)` | input; real mouse glide + real keystrokes; password fields refused; `win+l` blocked; own windows refused |
| `wait(seconds)` | interruptible sleep (needed for kill-switch tests; not in the original list) |
| `launch(app, args, cwd, wait_ms, user_requested_download?)`, `clipboard_get/set` | start things visibly (minimized windows restored), unicode clipboard |
| `run(command, shell, timeout, cwd, user_requested_download?)` | PowerShell or cmd, elevated, output capped at 100 KB |
| `fs(op, path, dest?, content?, ...)` | list/stat/read/write/mkdir/move/copy/delete; **delete = Recycle Bin only**; log + log tools protected |
| `audio_level(device?, probe_ms?)` | ~150 ms loopback probe of every output; reports the device with signal. Explicit and logged |
| `resume` | clear the kill switch (only when the user says so) |

### Coordinates

Screenshots are downscaled (long edge 1568). Pass `x,y` as pixels **of the last screenshot** (`coords='shot'`, the default) and the
server maps them to real pixels, including negative origins and 200 % scaling; or pass `coords='screen'` for real virtual-desktop
pixels. `ui_tree` rects are always real pixels. The mapping is a pure function in `desktop_bridge/coords.py`, unit-tested for both monitors.

### Capture engines

DXGI Desktop Duplication (`dxcam`) first; `mss` (GDI) when DXGI fails, the region spans monitors, or the session is RDP. Every
screenshot reply names the engine and why. A static screen makes DXGI deliver no new frame, so the last frame is reused and reported as `dxcam(unchanged-frame)`.

## Safety summary (details in SECURITY.md)

Append-only action log queue - kill switch - password-field refusal (`[redacted]` in the log) - process denylist
(`KeePass*, Bitwarden*, 1Password*, Dashlane*, LastPass*`, input/UI/screenshot; screenshots black out those windows) - protected log
paths - Recycle Bin deletes - temp files under `%TEMP%\desktop-bridge\` older than 1 day go to the Recycle Bin at start.

## Tests

* `.venv\Scripts\python.exe -m unittest discover tests` - coordinate mapping (both monitors, negative origin, round trips), denylist,
  key parsing, protected paths, locked-session refusal.
* `.venv\Scripts\python.exe selftest.py [all|core|control|sessions]` - drives the real launcher + elevated worker over MCP (a temp approval store is seeded only if `config.json` equals the committed version).
  **It opens visible windows on both monitors, flashes the border, moves the mouse and types for ~8 minutes; run it only when the user is at the PC and has said OK.** It needs no input from the user.
  A real physical Esc press is NOT part of it (a user must do that once by hand).

## Not in M0

`screen_watch`/60 fps recording, `av_record`/correlation, processes/services/registry/scheduled tasks/event log/system info,
`batch`, drag/scroll/hold_key/mouse_move, Show Desktop. Those are M1-M3.


## Presence, visibility and the injection gate (M0.1 - M0.3)

**You can always see and stop what Grok does.**
* **"In control" window.** From the start of any tool call (except `session_status`, `monitors_list`, `resume`) until `control.idle_grace_s` (default 8 s) after the last one.
* **White pulsing border + label.** While in control, every monitor gets a topmost, click-through, no-activate, ~6 px (DPI scaled: 12 px on the 200 % TV) white border that pulses grey↔white and a pill
  at the top: "Grok is using your computer. Press Esc to Stop". It appears >= 150 ms before the first action of a burst, disappears after the grace period, turns **red**
  ("Stopped by you" / "Stopped for safety") when stopped. The overlay is excluded from the bridge's own screenshots (`WDA_EXCLUDEFROMCAPTURE`), which also hides it from
  display-capture tools; your eyes and a phone camera still see it. If it cannot be created, input tools refuse with `OVERLAY_UNAVAILABLE` (fail closed).
* **Esc stops everything.** While Grok is in control, a press of Esc halts all actions within ~50-100 ms (waits, mouse glides, typing mid-string, `run`), the border turns red and every call is refused until
  `desktop_resume`. Esc is *polled* (`GetAsyncKeyState`, every 25 ms, only while in control): no `RegisterHotKey`, no keyboard hook, so the key always reaches the app you are using.
  The bridge's own injected Esc (`desktop_key esc`) is ignored (timestamps; a real Esc within ~120 ms of it is also ignored). `Ctrl+Alt+Pause` and `Ctrl+Alt+Shift+K` still work any time.
* **The mouse is the real mouse.** Pointer actions glide the real cursor (120-300 ms, eased), draw a halo, then click. `click(ref)` clicks the element's centre with the real mouse; nothing is "invoked" silently.
* **Typing is visible.** `type` clicks the field (if you pass a ref) and types real keystrokes at ~8 ms/char. `method="value"` (ValuePattern.SetValue) is opt-in, needs a ref, only for >= 200 chars, and is announced in the feed. **This changes M0:** the old default was SetValue.
* **Self-protection.** `click/type/key/window_focus` aimed at the bridge's own feed window or overlay are refused (`SELF_TARGET_REFUSED`), so Grok cannot answer its prompts.
* **The feed window is never hidden:** it starts on the primary monitor; if minimized/hidden/off-screen when a call arrives it is restored without taking focus. `session_status.feed_window` reports it.
* **Nothing hidden:** `run` executes in the visible feed console. Refused with `HIDDEN_EXECUTION_REFUSED`: `-WindowStyle Hidden|Minimized`, `start /min|/b`, `wscript|cscript //B`, `pythonw`, `mshta`, `Start-Job`/`-AsJob`, `CreateNoWindow`, and
  scheduled-task/service creation (only with `user_requested_download=true`, as specified). Also refused: shell input synthesis (`INPUT_BYPASS_REFUSED`) and shell commands that write protected policy files (`PROTECTED_PATH`).
  `launch` opens apps in a normal window state (restores minimized windows, reports `visible_window:false` if none appeared). **These are best-effort pattern checks, not a security boundary.**
* **No background downloads.** `config.json` `downloads: "ask"`. Anything that fetches from the network (Invoke-WebRequest/iwr/irm, curl, wget, bitsadmin, certutil -urlcache, Start-BitsTransfer, WebClient/DownloadFile, pip/npm/winget/choco install,
  git clone) is refused with `DOWNLOAD_NEEDS_USER_REQUEST` unless the call passes `user_requested_download=true` (the caller sets it only when the user's own chat message asks for that download). When allowed, the feed prints it prominently and the log records `DOWNLOAD user_requested`.
  Policy: installs only via `winget` with the exact package id; otherwise the user clicks Download on the official page.

**Injection gate (no toggle).** Text returned from the screen, files, clipboard, window titles or commands is labelled `untrusted: true` and scanned for instruction-injection signatures. Strong match: the content is **withheld**, the bridge locks itself (`source=injection`), the feed shows a red alert
(tool, window/element/file, <= 120-char escaped excerpt), the log records it, and **`desktop_resume` refuses** (`INJECTION_LOCKOUT`). Only the user can resume, by typing `y` at "Resume? (y/N)" in the feed window. Weak matches are labelled and logged only.
No setting, flag or parameter relaxes this. Text *inside images* cannot be scanned (no OCR in v1).

**Config approval.** `config.json` (+ `config.local.json`) are hashed; the hash of the version you last approved is stored in `%ProgramData%\GrokDesktopBridge\state\config.approved.json`. If the config is new or changed, the feed window shows what changed and asks
`Approve changed config? (y/N)`; **no tool works until you answer**. `config.json`, `SKILL.md`, `SECURITY.md` and the approval store are on the protected-paths list (`fs` refuses writes, `run` refuses non-read-only commands touching them).

**Optional hard lock (do NOT let Grok run this; you run it yourself in an elevated PowerShell).** The worker runs as your account, elevated, so software checks can in theory be bypassed. An ACL makes accidental or casual edits impossible; it is not a boundary against an elevated process of the same account:
```
icacls "C:\Users\SysAdmin\tools\grok-desktop-bridge\config.json" /inheritance:r /grant:r "SYSTEM:(R)" "Administrators:(R)"
icacls "C:\Users\SysAdmin\tools\grok-desktop-bridge\skills" /inheritance:r /grant:r "SYSTEM:(RX)" "Administrators:(RX)" /T
icacls "C:\Users\SysAdmin\tools\grok-desktop-bridge\SECURITY.md" /inheritance:r /grant:r "SYSTEM:(R)" "Administrators:(R)"
```
To edit later: `icacls <path> /grant "Administrators:(F)"` (then re-run the lock). A real boundary needs a separate account that owns these files.

**Test hooks (can only make the bridge stricter or test a different approval store):** `DESKTOP_BRIDGE_FORCE_OVERLAY_FAIL=1` (worker `--force-overlay-fail`) and `DESKTOP_BRIDGE_APPROVAL_DIR` (worker `--approval-dir`). Neither relaxes the injection gate or any policy.
**Shared environment (awareness, yield, never fight).** Every step of a glide, key press and typed character checks the kill switch and that the target window still exists (`TARGET_CLOSED` if you closed it); typing also needs the keyboard focus to stay
with the target (`FOCUS_CHANGED` if you switched windows; the bridge does not steal focus back) and no keys/mouse buttons held by you in that window (`USER_INTERVENTION`; media/volume/browser keys are ignored, so changing a song or closing an unrelated window does not matter). Stops carry `data` (foreground_now, target_alive, typed, remaining). A bump of the mouse during a glide is waited out (`control.yield_wait_s`, default 6 s, until it is still for 0.5 s), then the glide restarts; a click is cancelled if the cursor is not where the bridge put it. Closing the feed window stops the worker and the session.
**mcp SDK quirk fixed:** `desktop_bridge/mcp_patch.py` stops the SDK from JSON-parsing string arguments such as `{}` or `[1,2]` (it would have broken writing JSON files with `fs`, `type`, `clipboard_set`).

## Remote mode (implemented) — Grok Bot cloud only

Opt-in localhost MCP streamable-HTTP + outbound tunnel. **Production use is remote Grok only** (local stdio remains for selftest).

* **Start:** `python launcher.py --remote --port 8790` (binds `127.0.0.1`; default instance `grok`).
* **Grok-only gate:** every request needs `Authorization: Bearer <token>` **and** `X-Grok-Bridge-Client: grok-bot`. Blocked User-Agents / MCP `clientInfo` for Claude, Codex, Cursor, etc. yield **403**.
* **Tokens:** `--add-bot` / `--list-bots` / `--revoke-bot` under `%LOCALAPPDATA%\GrokDesktopBridge\remote_bots.json`.
* **Isolation:** separate pipes/mutexes/AppData/temp/task from Claude `desktop-mcp-bridge` (see `desktop_bridge/brand.py`).
* **Tunnel:** `cloudflared tunnel --url http://127.0.0.1:8790`.
* **Do not** share the tunnel URL + token with other people, free/browser accounts, or other AI products — that hands over the PC.
* **Docs:** [`docs/REMOTE_QUICKSTART.md`](docs/REMOTE_QUICKSTART.md), `skills/grok-bridge-client/SKILL.md`.

