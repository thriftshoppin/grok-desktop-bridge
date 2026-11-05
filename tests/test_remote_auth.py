"""Linux-safe tests for remote bearer tokens, Grok-only gate, and HTTP 401/403."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from desktop_bridge import brand  # noqa: E402
from desktop_bridge.remote_auth import (  # noqa: E402
    BotTokenStore,
    extract_bearer,
    generate_token,
    token_ok,
    validate_bot_name,
)
from desktop_bridge.remote_http import (  # noqa: E402
    SessionTransport,
    client_header_ok,
    client_info_allowed,
    looks_blocked_client,
    reject_non_grok_http,
    run_until_stopped,
    serve_remote,
)


class TokenHelpers(unittest.TestCase):
    def test_compare_digest_rejects_wrong_and_none(self):
        t = generate_token()
        self.assertTrue(token_ok(t, t))
        self.assertFalse(token_ok(t, t[:-1] + ("A" if t[-1] != "A" else "B")))
        self.assertFalse(token_ok(t, None))
        self.assertFalse(token_ok(t, ""))
        self.assertFalse(token_ok("", t))

    def test_extract_bearer(self):
        self.assertEqual(extract_bearer("Bearer abc"), "abc")
        self.assertEqual(extract_bearer("bearer abc"), "abc")
        self.assertIsNone(extract_bearer("Basic abc"))
        self.assertIsNone(extract_bearer(None))

    def test_bot_name_validation(self):
        self.assertEqual(validate_bot_name("alice"), "alice")
        self.assertEqual(validate_bot_name("Work-Bot_1"), "Work-Bot_1")
        with self.assertRaises(ValueError):
            validate_bot_name("../x")
        with self.assertRaises(ValueError):
            validate_bot_name("")


class GrokOnlyGate(unittest.TestCase):
    def test_client_header(self):
        self.assertTrue(client_header_ok("grok-bot"))
        self.assertTrue(client_header_ok("local-computer-assistant"))
        self.assertFalse(client_header_ok(None))
        self.assertFalse(client_header_ok("claude-desktop"))
        self.assertFalse(client_header_ok("cursor"))

    def test_blocked_markers(self):
        self.assertTrue(looks_blocked_client("Claude Desktop/1.0"))
        self.assertTrue(looks_blocked_client("codex-cli"))
        self.assertTrue(looks_blocked_client("Cursor/1.0"))
        self.assertFalse(looks_blocked_client("grok-bot/1.0"))
        self.assertFalse(looks_blocked_client(None))

    def test_client_info(self):
        self.assertTrue(client_info_allowed("Grok"))
        self.assertTrue(client_info_allowed("Local Computer Assistant"))
        self.assertTrue(client_info_allowed(None))
        self.assertFalse(client_info_allowed("Claude Desktop"))
        self.assertFalse(client_info_allowed("Codex"))
        self.assertFalse(client_info_allowed("Cursor"))

    def test_reject_helper(self):
        class H(dict):
            def get(self, k, default=None):
                return super().get(k, default)

        self.assertIsNotNone(reject_non_grok_http(H()))
        self.assertIsNotNone(reject_non_grok_http(H({"User-Agent": "Claude Desktop"})))
        self.assertIsNone(reject_non_grok_http(H({brand.CLIENT_HEADER: "grok-bot"})))


class BotStore(unittest.TestCase):
    def test_add_list_revoke_resolve(self):
        with tempfile.TemporaryDirectory() as d:
            store = BotTokenStore(Path(d) / "bots.json")
            tok_a, created = store.add_bot("alice")
            self.assertTrue(created)
            tok_b, _ = store.add_bot("bob")
            self.assertEqual({b["name"] for b in store.list_bots()}, {"alice", "bob"})
            self.assertEqual(store.resolve(tok_a), "alice")
            self.assertEqual(store.resolve(tok_b), "bob")
            self.assertIsNone(store.resolve("nope"))
            tok_a2, created2 = store.add_bot("alice")
            self.assertFalse(created2)
            self.assertNotEqual(tok_a, tok_a2)
            self.assertIsNone(store.resolve(tok_a))
            self.assertTrue(store.revoke_bot("bob"))


def _factory_echo(bot: str) -> SessionTransport:
    q_out: list[bytes] = []

    def write_bytes(data: bytes) -> None:
        msg = json.loads(data.decode())
        if "id" in msg:
            q_out.append(
                (json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": {"ok": True, "bot": bot}}) + "\n").encode()
            )

    def read_line() -> bytes:
        for _ in range(200):
            if q_out:
                return q_out.pop(0)
            time.sleep(0.01)
        return b""

    return SessionTransport(write_bytes, read_line, bot=bot)


class RemoteHTTPAuth(unittest.TestCase):
    def _start(self, store):
        stop = threading.Event()
        httpd = serve_remote("127.0.0.1", 0, store, _factory_echo, stop_event=stop)
        port = httpd.server_address[1]
        th = threading.Thread(target=run_until_stopped, args=(httpd,), daemon=True)
        th.start()
        return httpd, stop, th, port

    def _post(self, port, token, extra_headers=None, body=None):
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        if extra_headers:
            headers.update(extra_headers)
        data = body or b'{"jsonrpc":"2.0","id":1,"method":"ping"}'
        return urllib.request.urlopen(
            urllib.request.Request(
                f"http://127.0.0.1:{port}/mcp", data=data, headers=headers, method="POST"
            ),
            timeout=5,
        )

    def test_rejects_non_grok_and_bad_token(self):
        with tempfile.TemporaryDirectory() as d:
            store = BotTokenStore(Path(d) / "bots.json")
            token, _ = store.add_bot("alice")
            httpd, stop, th, port = self._start(store)
            try:
                with self.assertRaises(urllib.error.HTTPError) as cm:
                    self._post(port, token)
                self.assertEqual(cm.exception.code, 403)

                with self.assertRaises(urllib.error.HTTPError) as cm:
                    self._post(
                        port,
                        token,
                        {brand.CLIENT_HEADER: "grok-bot", "User-Agent": "Claude Desktop/1.0"},
                    )
                self.assertEqual(cm.exception.code, 403)

                with self.assertRaises(urllib.error.HTTPError) as cm:
                    self._post(port, "wrong-token-value-xxxxxxxxxxxx", {brand.CLIENT_HEADER: "grok-bot"})
                self.assertEqual(cm.exception.code, 401)

                resp = self._post(port, token, {brand.CLIENT_HEADER: "grok-bot"})
                body = json.loads(resp.read().decode())
                self.assertEqual(body["result"]["bot"], "alice")

                init = json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "initialize",
                        "params": {"clientInfo": {"name": "Claude Desktop", "version": "1"}},
                    }
                ).encode()
                with self.assertRaises(urllib.error.HTTPError) as cm:
                    self._post(port, token, {brand.CLIENT_HEADER: "grok-bot"}, body=init)
                self.assertEqual(cm.exception.code, 403)
            finally:
                stop.set()
                try:
                    httpd.shutdown()
                except Exception:
                    pass
                th.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
