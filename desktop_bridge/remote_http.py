"""Localhost-only MCP streamable-HTTP front for the Grok Desktop Bridge.

Stdlib only (http.server). Binds 127.0.0.1, requires a per-bot Bearer token on
every request, relays JSON-RPC to a newline-delimited MCP session per bot (the
guardian pipe, or a test double). Multiple bots share one HTTP listener and the
same guardian / feed / Esc kill switch; each call is tagged with the bot name.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import urlparse

from . import brand
from .remote_auth import BotTokenStore, extract_bearer

# Origins we accept when the Origin header is present (DNS-rebinding guard).
_LOCAL_ORIGINS = {
    "http://127.0.0.1",
    "http://localhost",
    "https://127.0.0.1",
    "https://localhost",
    "null",
}

_MISSING = object()


class SessionTransport:
    """Thread-safe NDJSON MCP session over a bidirectional byte stream pair."""

    def __init__(
        self,
        write_bytes: Callable[[bytes], None],
        read_line: Callable[[], bytes],
        on_event: Callable[[str], None] | None = None,
        bot: str = "",
    ):
        self.bot = bot
        self._write = write_bytes
        self._read_line = read_line
        self._on_event = on_event or (lambda _s: None)
        self._lock = threading.Lock()
        self._pending: dict[Any, threading.Event] = {}
        self._results: dict[Any, dict] = {}
        self._closed = threading.Event()
        self._reader = threading.Thread(target=self._read_loop, name=f"mcp-pipe-{bot or 'x'}", daemon=True)
        self._reader.start()

    @property
    def closed(self) -> bool:
        return self._closed.is_set()

    def close(self) -> None:
        self._closed.set()
        with self._lock:
            for ev in self._pending.values():
                ev.set()

    def _read_loop(self) -> None:
        try:
            while not self._closed.is_set():
                line = self._read_line()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = line.decode("utf-8", "replace") if isinstance(line, (bytes, bytearray)) else line
                    msg = json.loads(raw)
                except Exception:
                    continue
                if not isinstance(msg, dict):
                    continue
                mid = msg.get("id", _MISSING)
                if mid is _MISSING:
                    self._on_event(f"[{self.bot}] remote MCP notification: {msg.get('method', '?')}")
                    continue
                with self._lock:
                    self._results[mid] = msg
                    ev = self._pending.get(mid)
                    if ev:
                        ev.set()
        finally:
            self.close()

    def call(self, message: dict, timeout: float = 600.0) -> dict | None:
        if self.closed:
            raise RuntimeError("MCP session is closed")
        mid = message.get("id", _MISSING)
        is_request = mid is not _MISSING
        raw = (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")
        ev = None
        if is_request:
            ev = threading.Event()
            with self._lock:
                self._pending[mid] = ev
                self._results.pop(mid, None)
        try:
            with self._lock:
                self._write(raw)
            method = message.get("method", "?")
            tag = f"[{self.bot}] " if self.bot else ""
            self._on_event(tag + f"remote MCP call: {method}" + (f" id={mid}" if is_request else " (notification)"))
            if not is_request:
                return None
            if not ev.wait(timeout):
                raise TimeoutError(f"no response for MCP id={mid} within {timeout}s")
            if self.closed and mid not in self._results:
                raise RuntimeError("MCP session closed while waiting for response")
            with self._lock:
                return self._results.pop(mid, None)
        finally:
            if is_request:
                with self._lock:
                    self._pending.pop(mid, None)


SessionFactory = Callable[[str], SessionTransport]
# factory(bot_name) -> SessionTransport for that bot (opens a guardian session)



def _norm_client(s: str | None) -> str:
    return (s or "").strip().lower()


def client_header_ok(value: str | None) -> bool:
    return _norm_client(value) in brand.ALLOWED_CLIENT_HEADERS


def looks_blocked_client(text: str | None) -> bool:
    t = _norm_client(text)
    if not t:
        return False
    return any(m in t for m in brand.BLOCKED_CLIENT_MARKERS)


def client_info_allowed(name: str | None) -> bool:
    """True if missing (some HTTP probes) or clearly a Grok / Local Computer Assistant client."""
    if name is None or str(name).strip() == "":
        return True  # header gate is mandatory; initialize checked when name present
    n = _norm_client(name)
    if looks_blocked_client(n):
        return False
    if n in brand.ALLOWED_CLIENT_INFO_NAMES:
        return True
    # allow names that start with grok / local computer assistant
    if n.startswith("grok") or n.startswith("local computer assistant") or n.startswith("local-computer-assistant"):
        return True
    return False


def reject_non_grok_http(headers) -> str | None:
    """Return an error message if this remote HTTP client is not a Grok Bot; else None."""
    ua = headers.get("User-Agent") if hasattr(headers, "get") else None
    if looks_blocked_client(ua):
        return "remote mode is Grok Bot only; this User-Agent is not allowed"
    hdr = None
    if hasattr(headers, "get"):
        hdr = headers.get(brand.CLIENT_HEADER) or headers.get(brand.CLIENT_HEADER.lower())
    if not client_header_ok(hdr):
        return (
            f"remote mode is Grok Bot only; missing or invalid {brand.CLIENT_HEADER} "
            f"(expected one of: {', '.join(sorted(brand.ALLOWED_CLIENT_HEADERS))})"
        )
    return None


def origin_allowed(origin: str | None) -> bool:
    if origin is None or origin == "":
        return True
    o = origin.strip().rstrip("/")
    if o in _LOCAL_ORIGINS:
        return True
    try:
        u = urlparse(origin)
    except Exception:
        return False
    if u.scheme in ("http", "https") and (u.hostname or "").lower() in ("127.0.0.1", "localhost", "::1"):
        return True
    return False


class RemoteHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        host: str,
        port: int,
        store: BotTokenStore,
        session_factory: SessionFactory,
        on_log: Callable[[str], None] | None = None,
        stop_event: threading.Event | None = None,
    ):
        self.store = store
        self.session_factory = session_factory
        self.on_log = on_log or (lambda _s: None)
        self.stop_event = stop_event or threading.Event()
        self._sessions: dict[str, SessionTransport] = {}
        self._sessions_lock = threading.Lock()
        self._announced: set[str] = set()
        super().__init__((host, port), _RemoteHandler)

    def transport_for(self, bot: str) -> SessionTransport:
        with self._sessions_lock:
            t = self._sessions.get(bot)
            if t is not None and not t.closed:
                return t
            t = self.session_factory(bot)
            self._sessions[bot] = t
            return t

    def close_all_sessions(self) -> None:
        with self._sessions_lock:
            items = list(self._sessions.values())
            self._sessions.clear()
        for t in items:
            try:
                t.close()
            except Exception:
                pass

    def service_actions(self) -> None:
        if self.stop_event.is_set():
            threading.Thread(target=self.shutdown, daemon=True).start()


class _RemoteHandler(BaseHTTPRequestHandler):
    server: RemoteHTTPServer

    def log_message(self, fmt: str, *args) -> None:
        self.server.on_log("http: " + (fmt % args))

    def _reject(self, code: int, msg: str) -> None:
        body = json.dumps({"error": msg}).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _authenticate(self) -> str | None:
        if not origin_allowed(self.headers.get("Origin")):
            self._reject(403, "Origin not allowed")
            return None
        why = reject_non_grok_http(self.headers)
        if why:
            self._reject(403, why)
            return None
        provided = extract_bearer(self.headers.get("Authorization"))
        bot = self.server.store.resolve(provided)
        if bot is None:
            self._reject(401, "Unauthorized: Bearer token required")
            return None
        return bot

    def _path(self) -> str:
        return urlparse(self.path).path.rstrip("/") or "/"

    def do_GET(self) -> None:  # noqa: N802
        if self._path() not in ("/mcp", "/"):
            self._reject(404, "not found")
            return
        bot = self._authenticate()
        if bot is None:
            return
        body = json.dumps({
            "ok": True,
            "name": "grok-desktop-bridge",
            "bot": bot,
            "transport": "streamable-http",
            "message": "POST JSON-RPC to /mcp with Authorization: Bearer <bot-token> and X-Grok-Bridge-Client: grok-bot",
            "grok_only": True,
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        if self._path() not in ("/mcp", "/"):
            self._reject(404, "not found")
            return
        bot = self._authenticate()
        if bot is None:
            return
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0 or length > 16_000_000:
            self._reject(400, "bad Content-Length")
            return
        raw = self.rfile.read(length)
        try:
            message = json.loads(raw.decode("utf-8"))
        except Exception:
            self._reject(400, "body must be JSON-RPC")
            return
        if not isinstance(message, dict):
            self._reject(400, "body must be a JSON-RPC object")
            return

        if message.get("method") == "initialize":
            params = message.get("params") or {}
            info = (params.get("clientInfo") or {}) if isinstance(params, dict) else {}
            cname = info.get("name") if isinstance(info, dict) else None
            if not client_info_allowed(cname):
                self.server.on_log(f"[{bot}] rejected non-Grok MCP clientInfo.name={cname!r}")
                self._reject(403, "remote mode is Grok Bot / Local Computer Assistant only; MCP clientInfo rejected")
                return

        if bot not in self.server._announced:
            self.server._announced.add(bot)
            self.server.on_log(f"Remote session connected: bot={bot}")

        if self.server.stop_event.is_set():
            self._reject(503, "bridge stopped (kill switch or session closed)")
            return

        try:
            transport = self.server.transport_for(bot)
        except Exception as e:
            self.server.on_log(f"[{bot}] failed to open guardian session: {e}")
            self._reject(503, f"cannot open bridge session: {e}")
            return

        if transport.closed:
            self._reject(503, "bridge session closed")
            return

        is_notification = "id" not in message
        try:
            result = transport.call(message)
        except Exception as e:
            self.server.on_log(f"[{bot}] remote MCP error: {e}")
            err = {
                "jsonrpc": "2.0",
                "id": message.get("id"),
                "error": {"code": -32000, "message": str(e)[:300]},
            }
            body = json.dumps(err).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self._maybe_trip_kill(result)

        if is_notification:
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        body = json.dumps(result if result is not None else {
            "jsonrpc": "2.0",
            "id": message.get("id"),
            "error": {"code": -32001, "message": "no response from guardian"},
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _maybe_trip_kill(self, result: dict | None) -> None:
        if not result:
            return
        text = json.dumps(result)
        if "KILL_SWITCH" in text or "INJECTION_LOCKOUT" in text:
            self.server.on_log("kill switch / injection lockout seen on remote call — stopping HTTP server (all bots)")
            self.server.stop_event.set()
            self.server.close_all_sessions()


def serve_remote(
    host: str,
    port: int,
    store: BotTokenStore,
    session_factory: SessionFactory,
    on_log: Callable[[str], None] | None = None,
    stop_event: threading.Event | None = None,
) -> RemoteHTTPServer:
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("remote mode must bind to loopback only")
    stop_event = stop_event or threading.Event()
    httpd = RemoteHTTPServer(host, port, store, session_factory, on_log=on_log, stop_event=stop_event)

    def _watch():
        while not stop_event.wait(0.5):
            pass
        try:
            httpd.close_all_sessions()
            httpd.shutdown()
        except Exception:
            pass

    threading.Thread(target=_watch, name="remote-stop-watch", daemon=True).start()
    (on_log or (lambda _s: None))(
        f"remote MCP listening on http://{host}:{port}/mcp (loopback only; per-bot Bearer token required)"
    )
    return httpd


def run_until_stopped(httpd: RemoteHTTPServer) -> None:
    try:
        httpd.serve_forever(poll_interval=0.5)
    finally:
        httpd.close_all_sessions()
        try:
            httpd.server_close()
        except Exception:
            pass
