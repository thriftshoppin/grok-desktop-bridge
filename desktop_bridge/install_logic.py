"""Pure decisions for from-scratch install, cleanup boundaries, process identity, and startup.

The Windows scripts in the repo root implement these rules. Unit tests cover the decisions;
they do not delete anything on a machine.
"""
from __future__ import annotations

import os
import re

# Known Folder GUIDs (SHGetKnownFolderPath). OneDrive Known Folder Move redirects these.
KNOWN_FOLDER_DESKTOP = "B4BFCC3A-DB2C-424C-B029-7FE99A87C641"
KNOWN_FOLDER_DOWNLOADS = "374DE290-123F-4565-9164-39C4925E467B"

CONFIRM_GROK = "REMOVE LISTED GROK INSTALLS"
CONFIRM_OTHER = "REMOVE LISTED GROK INSTALLS AND SELECTED OTHER CLIENT PATHS"

# CPython versions whose pinned requirements all have win_amd64 wheels.
# Verified against PyPI file lists for the pins in requirements.txt (2026-11-05):
#   dxcam==0.3.0     win_amd64 cp310–cp314 only (no win32, no cp315)
#   numpy==2.5.4     Requires-Python >=3.12, win_amd64 wheels
#   Pillow==13.0.0   Requires-Python >=3.11, win_amd64 wheels
#   pywin32==312, PyAudioWPatch==0.2.12.9 have cp314 win_amd64 wheels
# Intersection: 64-bit CPython 3.12, 3.13, 3.14.
SUPPORTED_CPYTHON = ((3, 12), (3, 13), (3, 14))

MAX_WALK_DEPTH = 6
INSTALL_DIR_NAME = "grok-desktop-bridge"
UAC_CANCELLED = 1223
REMOTE_PORT = 8790

_FOLDER_RE = re.compile(
    r"(?i)^(grok-desktop-bridge|desktop-mcp-bridge)(-main)?([ ._-]*(\(\d+\)|\d+))?$"
)
_SCRIPT_NAMES = {
    "apply-escfix.ps1": "grok-script",
    "grokbridge-lightswitch.ps1": "grok-script",
    "grokbridge-lightswitch.cmd": "grok-script",
    "update-grokbridgeinplace.ps1": "grok-script",
}
_SHORTCUT_NAME = "grok desktop bridge light switch.lnk"
_SERVER_OTHER_RE = re.compile(r"""SERVER_NAME\s*=\s*['"]desktop-mcp-bridge['"]""")
_SERVER_GROK_RE = re.compile(r"""SERVER_NAME\s*=\s*['"]grok-desktop-bridge['"]""")
_PRODUCT_GROK_RE = re.compile(r"""PRODUCT\s*=\s*['"]GrokDesktopBridge['"]""")
_TOKEN_ASSIGN_RE = re.compile(r"(?i)(\btoken\b\s*[:=]\s*)(\S+)")
_BEARER_RE = re.compile(r"(?i)(bearer\s+)([A-Za-z0-9._~+/-]{8,})")
_INSTANCE_GROK_RE = re.compile(r"(?i)--instance(?:\s+|=)grok\b")


def folder_name_matches(name: str) -> bool:
    return bool(_FOLDER_RE.match(name or ""))


def brand_markers(brand_text: str) -> tuple[bool, bool]:
    """(grok_product, other_client_product) from desktop_bridge/brand.py text only."""
    text = brand_text or ""
    grok = bool(_PRODUCT_GROK_RE.search(text) or _SERVER_GROK_RE.search(text))
    other = bool(_SERVER_OTHER_RE.search(text))
    return grok, other


def classify_dir(name: str, brand_text: str | None) -> str:
    """grok | other-client | ambiguous | ignore.

    desktop-mcp-bridge folders are other-client unless brand.py is clearly this Grok product.
    A folder that contains both products is ambiguous and is not wiped by the default phrase.
    """
    if not folder_name_matches(name):
        return "ignore"
    stem_other = (name or "").lower().startswith("desktop-mcp-bridge")
    grok, other = brand_markers(brand_text or "")
    if grok and other:
        return "ambiguous"
    if other and not grok:
        return "other-client"
    if grok:
        return "grok"
    if stem_other:
        return "other-client"
    return "grok"


def classify_file(name: str) -> str:
    return _SCRIPT_NAMES.get((name or "").lower(), "ignore")


def classify_shortcut(name: str, target_path: str | None) -> str:
    if (name or "").lower() != _SHORTCUT_NAME:
        return "ignore"
    target = (target_path or "").replace("/", "\\").lower()
    if "desktop-mcp-bridge" in target and "grok-desktop-bridge" not in target:
        return "ambiguous"
    return "grok-shortcut"


def norm(path: str) -> str:
    """Case-fold and use backslashes, without joining the local working directory.

    Windows paths then compare the same way on a Linux test host and on the PC.
    """
    raw = (path or "").strip().replace("/", "\\")
    while "\\\\" in raw:
        raw = raw.replace("\\\\", "\\")
    return raw.rstrip("\\").lower()


def is_within(child: str, parent: str) -> bool:
    if not child or not parent:
        return False
    c, p = norm(child), norm(parent)
    return c == p or c.startswith(p + "\\")


def walk_tree(nodes: list[dict], max_depth: int = MAX_WALK_DEPTH) -> list[dict]:
    """Yield nodes from a discovery tree without entering reparse points or exceeding depth.

    Each node: path, name, is_dir, is_reparse, brand_text (optional), target_path (optional), children.
    """
    found: list[dict] = []

    def rec(items: list[dict], depth: int) -> None:
        if depth > max_depth:
            return
        for node in items:
            found.append(node)
            if node.get("is_reparse"):
                continue
            if node.get("is_dir") and node.get("children") and depth < max_depth:
                rec(node["children"], depth + 1)

    rec(nodes or [], 1)
    return found


def _action_for(cls: str, path: str, include_other: set[str]) -> str:
    if cls in ("grok", "grok-script", "grok-shortcut", "token-store", "state", "temp", "scheduled-task", "install-dir"):
        return "remove"
    if cls in ("other-client", "ambiguous") and norm(path) in include_other:
        return "remove"
    if cls in ("other-client", "ambiguous", "skip-reparse", "protected"):
        return "skip"
    return "skip"


def build_cleanup_plan(
    roots: list[dict],
    *,
    protected_roots: list[str],
    include_other_paths: list[str] | None = None,
    explicit_targets: list[dict] | None = None,
    max_depth: int = MAX_WALK_DEPTH,
) -> list[dict]:
    """Return ordered plan entries.

    entry keys: path, name, class, action (remove|skip), reason.
    A directory selected for removal covers its children; children are not separate remove entries.
    Reparse points are never entered and never given action remove.
    """
    include_other = {norm(p) for p in (include_other_paths or [])}
    protected = [p for p in protected_roots if p]
    plan: list[dict] = []
    covered: list[str] = []

    def covered_by_removed_parent(path: str) -> bool:
        return any(is_within(path, parent) and norm(path) != norm(parent) for parent in covered)

    for node in walk_tree(roots, max_depth=max_depth):
        path = node.get("path") or ""
        name = node.get("name") or os.path.basename(path)
        if any(is_within(path, p) for p in protected):
            if folder_name_matches(name) or classify_file(name) != "ignore":
                plan.append({
                    "path": path, "name": name, "class": "protected", "action": "skip",
                    "reason": "inside the installer package that is running",
                })
            continue
        if covered_by_removed_parent(path):
            continue
        if node.get("is_reparse"):
            interesting = folder_name_matches(name) or classify_file(name) != "ignore"
            if interesting:
                plan.append({
                    "path": path, "name": name, "class": "skip-reparse", "action": "skip",
                    "reason": "reparse point (junction/symlink); not entered and not deleted",
                })
            continue
        if node.get("is_dir"):
            cls = classify_dir(name, node.get("brand_text"))
        else:
            cls = classify_file(name)
            if cls == "ignore":
                cls = classify_shortcut(name, node.get("target_path"))
        if cls == "ignore":
            continue
        action = _action_for(cls, path, include_other)
        reason = cls
        if cls == "other-client":
            reason = "folder looks like another client's install (Claude/Codex desktop-mcp-bridge); not removed unless selected"
        elif cls == "ambiguous":
            reason = "folder contains both Grok and another client; not removed unless selected"
        plan.append({"path": path, "name": name, "class": cls, "action": action, "reason": reason})
        if action == "remove" and node.get("is_dir"):
            covered.append(path)

    for item in explicit_targets or []:
        path = item.get("path") or item.get("name") or ""
        if item.get("exists") is False:
            continue
        if any(is_within(path, p) for p in protected):
            plan.append({
                "path": path, "name": item.get("name") or os.path.basename(path),
                "class": "protected", "action": "skip",
                "reason": "explicit target is inside the running installer package",
            })
            continue
        if covered_by_removed_parent(path) or any(norm(path) == norm(p["path"]) and p["action"] == "remove" for p in plan):
            continue
        cls = item.get("class") or "state"
        plan.append({
            "path": path,
            "name": item.get("name") or os.path.basename(path.rstrip("\\/")),
            "class": cls,
            "action": "remove",
            "reason": item.get("reason") or cls,
        })
        if cls == "install-dir":
            covered.append(path)
    return plan


def needs_other_phrase(plan: list[dict]) -> bool:
    return any(p["action"] == "remove" and p["class"] in ("other-client", "ambiguous") for p in plan)


def confirmation_ok(phrase: str, plan: list[dict]) -> bool:
    phrase = phrase or ""
    if needs_other_phrase(plan):
        return phrase == CONFIRM_OTHER
    if any(p["action"] == "remove" for p in plan):
        return phrase == CONFIRM_GROK
    return True


def assess_python(version: tuple[int, ...], bits: int, implementation: str = "CPython") -> dict:
    """Return {ok, reason}. version is (major, minor) or longer. bits is 32 or 64."""
    impl = (implementation or "").strip()
    mm = (int(version[0]), int(version[1])) if len(version) >= 2 else (0, 0)
    if impl.lower() != "cpython":
        return {
            "ok": False,
            "reason": (
                f"Need CPython, found {impl or 'unknown'}. Install 64-bit CPython 3.14, 3.13, or 3.12 "
                "from python.org (not a store stub). dxcam and numpy ship CPython wheels only."
            ),
        }
    if int(bits) != 64:
        return {
            "ok": False,
            "reason": (
                f"This interpreter is {bits}-bit. dxcam==0.3.0 publishes win_amd64 wheels only "
                "(no 32-bit wheel). Install 64-bit CPython 3.14, 3.13, or 3.12."
            ),
        }
    if mm < (3, 12):
        return {
            "ok": False,
            "reason": (
                f"Python {mm[0]}.{mm[1]} is too old for the pinned dependencies. "
                "numpy==2.5.4 requires Python >=3.12 and Pillow==13.0.0 requires >=3.11. "
                "Install 64-bit CPython 3.14, 3.13, or 3.12. The installer will not try to build from source."
            ),
        }
    if mm not in SUPPORTED_CPYTHON:
        return {
            "ok": False,
            "reason": (
                f"Python {mm[0]}.{mm[1]} has no usable wheel set for these pins. "
                "dxcam==0.3.0 has Windows wheels for CPython 3.10–3.14 only (no 3.15+ wheel), "
                "and numpy==2.5.4 requires >=3.12, so the supported set is 64-bit CPython 3.12, 3.13, and 3.14. "
                "Install one of those. The installer uses pip --only-binary=:all: and will not compile dxcam."
            ),
        }
    return {
        "ok": True,
        "reason": f"64-bit CPython {mm[0]}.{mm[1]} is in the supported set (3.12, 3.13, 3.14) with win_amd64 wheels.",
    }


def redact_text(text: str) -> str:
    """Redact bearer tokens and token assignments. Leave tunnel URLs and the <bot-token> placeholder."""
    if not text:
        return text
    text = _TOKEN_ASSIGN_RE.sub(r"\1[redacted]", text)
    text = _BEARER_RE.sub(r"\1[redacted]", text)
    return text


def runas_failure_action(winerror: int) -> str:
    """UAC Cancel is ERROR_CANCELLED (1223). Do not fall through to a scheduled task after a cancel."""
    if int(winerror) == UAC_CANCELLED:
        return "abort"
    return "try-scheduled-task"


def is_owned_grok_process(command_line: str, executable: str, bridge_root: str, port: int = REMOTE_PORT) -> bool:
    """True only for this install's remote launcher, its grok guardian, or cloudflared aimed at this port.

    Does not match unrelated python, node, or cloudflared tunnels to other ports.
    """
    cl = command_line or ""
    exe = executable or ""
    root = norm(bridge_root) if bridge_root else ""
    cln = (cl or "").replace("/", "\\").lower()
    exen = norm(exe)
    base = exen.split("\\")[-1] if exen else ""
    under = bool(root) and (root in cln or exen == root or exen.startswith(root + "\\"))
    if base in ("cloudflared.exe", "cloudflared"):
        return (f"127.0.0.1:{int(port)}" in cl) and ("--url" in cln) and ("tunnel" in cln)
    if "grokbridge-runremote.ps1" in cln or "grokbridge-runtunnel.ps1" in cln:
        return under or (root in cln)
    if not under:
        return False
    if base not in ("python.exe", "pythonw.exe", "python", "py.exe"):
        return False
    worker = ("desktop_bridge.worker" in cln) and ("--guardian" in cln) and bool(_INSTANCE_GROK_RE.search(cl))
    launcher = ("launcher.py" in cln) and ("--remote" in cln)
    return worker or launcher


def safe_to_stop(recorded: dict | None, current: dict | None) -> tuple[bool, str]:
    """Stop only when PID, creation time, and image still identify the process we recorded.

    A reused PID (same number, different creation time or image) is not stopped.
    """
    if not recorded:
        return False, "nothing-recorded"
    if current is None:
        return False, "already-exited"
    if int(recorded.get("pid") or -1) != int(current.get("pid") or -2):
        return False, "pid-mismatch"
    if str(recorded.get("creation") or "") != str(current.get("creation") or ""):
        return False, "pid-reused"
    rec_image = norm(recorded.get("image") or "")
    cur_image = norm(current.get("image") or "")
    if rec_image != cur_image:
        return False, "image-changed"
    return True, "ok"


def classify_startup(
    *,
    launcher_exit: int | None,
    log_text: str,
    http_status: int | None,
    guardian_owned: bool,
    tunnel_url: str | None,
    timed_out: bool,
) -> dict:
    """ready | wait | uac_cancelled | failed. rollback is true when a partial start must be undone."""
    text = (log_text or "").lower()
    uac = ("error 1223" in text) or ("uac was cancelled" in text) or launcher_exit == UAC_CANCELLED
    if uac:
        return {
            "state": "uac_cancelled",
            "rollback": True,
            "reason": "UAC was cancelled (error 1223). Partial startup is rolled back. The scheduled task is not used after Cancel.",
        }
    http_ok = http_status == 401
    url = (tunnel_url or "").strip()
    running = launcher_exit is None
    if http_ok and guardian_owned and url and running:
        return {
            "state": "ready",
            "rollback": False,
            "reason": "guardian, loopback HTTP (401 without a token), and tunnel URL are up",
        }
    if launcher_exit is not None:
        return {
            "state": "failed",
            "rollback": True,
            "reason": f"launcher exited {launcher_exit} before guardian, HTTP, and tunnel were all ready",
        }
    if timed_out:
        return {
            "state": "failed",
            "rollback": True,
            "reason": "timed out waiting for the guardian process, HTTP 401 on 127.0.0.1, and a trycloudflare URL",
        }
    return {"state": "wait", "rollback": False, "reason": "still starting"}


def rollback_pids(recorded: list[dict], current_by_pid: dict[int, dict]) -> list[int]:
    """PIDs that are still the same process we started and therefore may be stopped."""
    out = []
    for rec in recorded:
        pid = int(rec.get("pid") or -1)
        ok, _why = safe_to_stop(rec, current_by_pid.get(pid))
        if ok:
            out.append(pid)
    return out
