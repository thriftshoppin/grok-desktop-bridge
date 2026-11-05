"""Named bearer tokens for opt-in remote (localhost streamable-HTTP) mode.

Multi-bot: each bot gets a named token (`--add-bot <name>`). Every HTTP request
must present `Authorization: Bearer <token>`; the matching bot name tags feed
lines and logs. Tokens are compared with hmac.compare_digest (constant-time).
Stdlib only — unit-tested on Linux without Windows GUI dependencies.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

TOKEN_BYTES = 32
BOT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def default_store_path() -> Path:
    """Prefer LOCALAPPDATA on Windows; fall back to ~/.local/share on Unix."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME")
    if not base:
        base = os.path.join(os.path.expanduser("~"), ".local", "share")
    return Path(base) / "GrokDesktopBridge" / "remote_bots.json"


def generate_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def validate_bot_name(name: str) -> str:
    name = (name or "").strip()
    if not BOT_NAME_RE.match(name):
        raise ValueError(
            "bot name must be 1-64 chars: letters, digits, . _ - ; must start with alphanumeric"
        )
    return name


def extract_bearer(authorization_header: str | None) -> str | None:
    if not authorization_header:
        return None
    parts = authorization_header.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        return None
    return parts[1].strip()


def token_ok(expected: str, provided: str | None) -> bool:
    if not expected or provided is None:
        return False
    a = expected.encode("utf-8")
    b = provided.encode("utf-8")
    if len(a) != len(b):
        hmac.compare_digest(a, a)
        return False
    return hmac.compare_digest(a, b)


class BotTokenStore:
    """Thread-safe on-disk store of {bot_name: {token, created}}."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else default_store_path()
        self._lock = threading.Lock()

    def _load(self) -> dict:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            bots = raw.get("bots") if isinstance(raw, dict) else None
            return dict(bots) if isinstance(bots, dict) else {}
        except Exception:
            return {}

    def _save(self, bots: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"bots": bots}, indent=2) + "\n", encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def list_bots(self) -> list[dict]:
        with self._lock:
            bots = self._load()
            out = []
            for name, meta in sorted(bots.items()):
                out.append({
                    "name": name,
                    "created": (meta or {}).get("created", ""),
                    "token_prefix": ((meta or {}).get("token") or "")[:6] + "…",
                })
            return out

    def add_bot(self, name: str) -> tuple[str, bool]:
        """Return (token, created_new). Re-issuing rotates the token."""
        name = validate_bot_name(name)
        token = generate_token()
        with self._lock:
            bots = self._load()
            created_new = name not in bots
            bots[name] = {"token": token, "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
            self._save(bots)
        return token, created_new

    def revoke_bot(self, name: str) -> bool:
        name = validate_bot_name(name)
        with self._lock:
            bots = self._load()
            if name not in bots:
                return False
            del bots[name]
            self._save(bots)
            return True

    def resolve(self, provided: str | None) -> str | None:
        """Constant-time-ish match of bearer token against every stored bot. Returns bot name or None."""
        if provided is None:
            return None
        with self._lock:
            bots = self._load()
        matched = None
        # Always iterate all entries so timing does not leak which bot matched.
        for name, meta in bots.items():
            expected = (meta or {}).get("token") or ""
            if token_ok(expected, provided):
                matched = name
        return matched

    def ensure_default(self, name: str = "default") -> tuple[str, str, bool]:
        """If the store is empty, create `name` and return (name, token, created)."""
        with self._lock:
            bots = self._load()
            if bots:
                # return first bot's name + token (do not rotate)
                n = sorted(bots.keys())[0]
                return n, bots[n]["token"], False
        token, created = self.add_bot(name)
        return name, token, created
