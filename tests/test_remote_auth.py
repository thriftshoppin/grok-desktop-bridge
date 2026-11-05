"""Linux-safe tests for remote bearer tokens and HTTP 401 rejection."""
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
from desktop_bridge.remote_auth import (  # noqa: E402
    BotTokenStore,
    extract_bearer,
    generate_token,
    token_ok,
    validate_bot_name,
)
from desktop_bridge.remote_http import (  # noqa: E402
    SessionTransport,
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
            self.assertIsNone(store.resolve(None))
            # rotate
            tok_a2, created2 = store.add_bot("alice")
            self.assertFalse(created2)
            self.assertNotEqual(tok_a, tok_a2)
            self.assertIsNone(store.resolve(tok_a))
            self.assertEqual(store.resolve(tok_a2), "alice")
            self.assertTrue(store.revoke_bot("bob"))
            self.assertIsNone(store.resolve(tok_b))
            self.assertFalse(store.revoke_bot("bob"))


class RemoteHTTPAuth(unittest.TestCase):
    def test_rejects_missing_and_wrong_token(self):
        with tempfile.TemporaryDirectory() as d:
            store = BotTokenStore(Path(d) / "bots.json")
            token, _ = store.add_bot("alice")

            def factory(bot: str) -> SessionTransport:
                # Echo JSON-RPC id back — enough to prove auth gating, not MCP semantics.
                import io
                q_in: list[bytes] = []
                q_out = []

                def write_bytes(data: bytes) -> None:
                    q_in.append(data)
                    msg = json.loads(data.decode())
                    if "id" in msg:
                        q_out.append((json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": {"ok": True, "bot": bot}}) + "\n").encode())

                def read_line() -> bytes:
                    for _ in range(200):
                        if q_out:
                            return q_out.pop(0)
                        time.sleep(0.01)
                    return b""

                return SessionTransport(write_bytes, read_line, bot=bot)

            stop = threading.Event()
            httpd = serve_remote("127.0.0.1", 0, store, factory, stop_event=stop)
            port = httpd.server_address[1]
            th = threading.Thread(target=run_until_stopped, args=(httpd,), daemon=True)
            th.start()
            try:
                url = f"http://127.0.0.1:{port}/mcp"
                # no header
                with self.assertRaises(urllib.error.HTTPError) as cm:
                    urllib.request.urlopen(urllib.request.Request(url, data=b'{"jsonrpc":"2.0","id":1,"method":"ping"}',
                                                                  headers={"Content-Type": "application/json"}, method="POST"), timeout=5)
                self.assertEqual(cm.exception.code, 401)
                # wrong token
                with self.assertRaises(urllib.error.HTTPError) as cm:
                    urllib.request.urlopen(urllib.request.Request(
                        url, data=b'{"jsonrpc":"2.0","id":1,"method":"ping"}',
                        headers={"Content-Type": "application/json", "Authorization": "Bearer wrong-token-value-xxxxxxxxxxxx"},
                        method="POST"), timeout=5)
                self.assertEqual(cm.exception.code, 401)
                # good token
                resp = urllib.request.urlopen(urllib.request.Request(
                    url, data=b'{"jsonrpc":"2.0","id":7,"method":"ping"}',
                    headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
                    method="POST"), timeout=5)
                body = json.loads(resp.read().decode())
                self.assertEqual(body["id"], 7)
                self.assertEqual(body["result"]["bot"], "alice")
            finally:
                stop.set()
                try:
                    httpd.shutdown()
                except Exception:
                    pass
                th.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
