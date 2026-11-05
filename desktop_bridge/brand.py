"""Grok Desktop Bridge identity and isolation defaults.

Keeps this install from colliding with a coexisting Claude/Codex desktop-mcp-bridge
(different instance name, pipes, mutexes, AppData/ProgramData/temp, scheduled task, remote port).
Remote MCP HTTP is Grok Bot cloud only — see remote_http client gate.
"""
from __future__ import annotations

PRODUCT = "GrokDesktopBridge"
SERVER_NAME = "grok-desktop-bridge"
INSTANCE_DEFAULT = "grok"
REMOTE_HOST_DEFAULT = "127.0.0.1"
REMOTE_PORT_DEFAULT = 8790
PIPE_PREFIX = "grok-desktop-bridge"
MUTEX_START_PREFIX = "Local\\GrokDesktopBridgeStart"
MUTEX_GUARDIAN_PREFIX = "Local\\GrokDesktopBridgeGuardian"
TASK_NAME = "GrokDesktopBridgeWorker"
OVERLAY_CLASS = "GrokDesktopBridgeOverlay"
STATE_DIR_NAME = "GrokDesktopBridge"  # under ProgramData and LOCALAPPDATA
TEMP_DIR_DEFAULT = r"%TEMP%\GrokDesktopBridge"

# Required on every remote HTTP request. Grok Bot skill sends this; other MCP hosts will not.
CLIENT_HEADER = "X-Grok-Bridge-Client"
ALLOWED_CLIENT_HEADERS = frozenset({
    "grok-bot",
    "grok",
    "local-computer-assistant",
    "local_computer_assistant",
})

# MCP initialize clientInfo.name allowlist (case-insensitive substring / exact).
ALLOWED_CLIENT_INFO_NAMES = frozenset({
    "grok",
    "grok-bot",
    "grok bot",
    "grok-desktop-bridge",
    "local computer assistant",
    "local-computer-assistant",
})

# If clientInfo.name or User-Agent clearly looks like another desktop agent, refuse.
BLOCKED_CLIENT_MARKERS = (
    "claude",
    "anthropic",
    "codex",
    "openai",
    "cursor",
    "windsurf",
    "copilot",
    "cline",
    "continue.dev",
    "continue ",
    "aider",
    "vscode",
    "visual studio code",
)
