"""Grok Desktop Bridge launcher: stdio MCP relay, or opt-in --remote HTTP front.

Default (stdio): the process an MCP client (Grok relay, Claude desktop, Claude Code ...) starts.
A thin relay: finds the shared elevated guardian, asks for a session, relays stdin/stdout over named pipes.

Opt-in remote mode (`--remote`): serves the SAME tool set over MCP streamable-HTTP bound to
127.0.0.1 only, with per-bot Bearer tokens (`--add-bot` / `--list-bots` / `--revoke-bot`). Expose
via an outbound tunnel the user runs (e.g. cloudflared). Esc / kill switch stops the HTTP server
and every bot session. Python stdlib only for the launcher itself.
"""
import ctypes
import ctypes.wintypes as wt
import json
import msvcrt
import os
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
SELF_PID = os.getpid()
TASK_NAME = "DesktopBridgeWorker"
INSTANCE = os.environ.get("DESKTOP_BRIDGE_INSTANCE", "main")
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.CreateMutexW.restype = wt.HANDLE


def err(msg: str) -> None:
    sys.stderr.write(f"[grok-desktop-bridge launcher] {msg}\n")
    sys.stderr.flush()


class SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("fMask", wt.ULONG), ("hwnd", wt.HWND), ("lpVerb", wt.LPCWSTR), ("lpFile", wt.LPCWSTR),
                ("lpParameters", wt.LPCWSTR), ("lpDirectory", wt.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wt.HINSTANCE),
                ("lpIDList", ctypes.c_void_p), ("lpClass", wt.LPCWSTR), ("hkeyClass", wt.HKEY), ("dwHotKey", wt.DWORD),
                ("hIcon", wt.HANDLE), ("hProcess", wt.HANDLE)]


class UntrustedGuardian(RuntimeError):
    """The program that answers on the control pipe is not our guardian (DB-1). Never retried, never started over."""


HIGH_INTEGRITY = 0x3000


def _norm(p: str) -> str:
    return os.path.normcase(os.path.abspath(p)) if p else ""


def expected_images() -> set:
    """Images the real guardian can run as: the interpreter that started this launcher (the venv python.exe is a shim that starts the base interpreter)."""
    return {_norm(sys.executable), _norm(getattr(sys, "_base_executable", "") or sys.executable)}


def server_pid_of(f) -> int:
    pid = wt.DWORD(0)
    k32.GetNamedPipeServerProcessId.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
    if not k32.GetNamedPipeServerProcessId(msvcrt.get_osfhandle(f.fileno()), ctypes.byref(pid)):
        raise OSError(ctypes.get_last_error(), "GetNamedPipeServerProcessId failed")
    return pid.value


def process_image(pid: int) -> str:
    k32.OpenProcess.restype = wt.HANDLE
    h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = wt.DWORD(1024)
        return buf.value if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) else ""
    finally:
        k32.CloseHandle(h)


def process_integrity(pid: int):
    """Integrity RID of a process (0x2000 medium, 0x3000 high), or None when it cannot be read."""
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    k32.OpenProcess.restype = wt.HANDLE
    h = k32.OpenProcess(0x1000, False, pid)
    if not h:
        return None
    tok = wt.HANDLE()
    try:
        if not adv.OpenProcessToken(h, 0x8, ctypes.byref(tok)):  # TOKEN_QUERY
            return None
        sz = wt.DWORD(0)
        adv.GetTokenInformation(tok, 25, None, 0, ctypes.byref(sz))  # TokenIntegrityLevel
        buf = ctypes.create_string_buffer(sz.value)
        if not adv.GetTokenInformation(tok, 25, buf, sz, ctypes.byref(sz)):
            return None
        adv.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
        adv.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
        adv.GetSidSubAuthority.argtypes = [ctypes.c_void_p, wt.DWORD]
        adv.GetSidSubAuthority.restype = ctypes.POINTER(wt.DWORD)
        sid = ctypes.c_void_p.from_buffer(buf).value
        count = adv.GetSidSubAuthorityCount(sid)[0]
        return int(adv.GetSidSubAuthority(sid, count - 1)[0])
    finally:
        if tok.value:
            k32.CloseHandle(tok)
        k32.CloseHandle(h)


def check_guardian(image: str, integrity, allowed: set):
    """-> None if the pipe server may be our guardian, else the reason. Pure function (unit-tested)."""
    if not image:
        return "its program could not be identified"
    if _norm(image) not in allowed:
        return f"it runs {image}, not this bridge's Python interpreter"
    if integrity is None:
        return "its integrity level could not be read"
    if integrity < HIGH_INTEGRITY:
        return f"it is not elevated (integrity {integrity:#x}); the real guardian always runs at High integrity"
    return None


def verify_guardian(f) -> None:
    """DB-1: the control pipe name is predictable, so before sending anything check WHO owns the other end. Raises UntrustedGuardian."""
    try:
        pid = server_pid_of(f)
        why = check_guardian(process_image(pid), process_integrity(pid), expected_images())
    except Exception as e:
        pid, why = 0, f"the check itself failed ({type(e).__name__}: {e})"
    if why:
        raise UntrustedGuardian(f"refusing to talk to the program that owns the control pipe (pid {pid}): {why}. "
                                "It may be an impostor squatting the pipe name; nothing was sent to it.")


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def control_path() -> str:
    return r"\\.\pipe" + "\\" + f"desktop-bridge-ctl-{INSTANCE}-{os.environ.get('USERNAME', 'user').lower()}"


def start_guardian():
    """Start the elevated guardian (visible console). Returns a process handle or None. Raises RuntimeError when it cannot be started."""
    # VISIBLE by design: python.exe (console) with the live action feed; never pythonw / SW_HIDE.
    py = sys.executable
    plist = ["-m", "desktop_bridge.worker", "--guardian", "--instance", INSTANCE]
    if os.environ.get("DESKTOP_BRIDGE_FORCE_OVERLAY_FAIL"):  # test hook; can only make the guardian more restrictive
        plist.append("--force-overlay-fail")
    if os.environ.get("DESKTOP_BRIDGE_APPROVAL_DIR"):  # test hook: another state folder (config approval + client allow-list)
        plist += ["--approval-dir", os.environ["DESKTOP_BRIDGE_APPROVAL_DIR"]]
    if os.environ.get("DESKTOP_BRIDGE_IDLE_EXIT_S"):  # test hook: guardian exits that many seconds after its last client
        plist += ["--idle-exit-s", os.environ["DESKTOP_BRIDGE_IDLE_EXIT_S"]]
    params = subprocess.list2cmdline(plist)
    if is_admin():  # already elevated (e.g. started from an admin shell): no need for runas
        si = subprocess.STARTUPINFO()
        si.dwFlags = 1  # STARTF_USESHOWWINDOW
        si.wShowWindow = 4  # SW_SHOWNOACTIVATE
        subprocess.Popen([py] + plist, cwd=ROOT, creationflags=0x10, startupinfo=si)  # CREATE_NEW_CONSOLE
        return None
    sei = SHELLEXECUTEINFOW()
    sei.cbSize = ctypes.sizeof(sei)
    sei.fMask = 0x00000040  # SEE_MASK_NOCLOSEPROCESS
    sei.lpVerb = "runas"
    sei.lpFile = py
    sei.lpParameters = params
    sei.lpDirectory = ROOT
    sei.nShow = 4  # SW_SHOWNOACTIVATE: visible, but does not steal focus
    if ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei)):
        return sei.hProcess
    code = ctypes.get_last_error() or k32.GetLastError()
    err(f"runas failed (error {code}); trying the scheduled-task fallback '{TASK_NAME}'")
    r = subprocess.run(["schtasks", "/run", "/tn", TASK_NAME], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"cannot start the elevated guardian: runas error {code}; task '{TASK_NAME}' not runnable "
                           f"({(r.stderr or r.stdout).strip()[:120]}). Run install-elevated-task.ps1 once.")
    return None


def try_open_control():
    """-> an open pipe, None if no guardian is running, or False if it is running but momentarily busy (retry; never start a second guardian)."""
    try:
        f = open(control_path(), "r+b", buffering=0)
    except FileNotFoundError:
        return None
    except OSError as e:
        if getattr(e, "winerror", 0) == 231 or e.errno == 22:  # ERROR_PIPE_BUSY: the guardian is between two pipe instances
            return False
        return None
    try:
        verify_guardian(f)   # DB-1: authenticate the other end before anything is sent
    except BaseException:
        f.close()
        raise
    return f


def open_existing(deadline: float):
    """Open the control pipe of a RUNNING guardian, waiting out 'busy'. Returns the pipe, or None if no guardian is running."""
    while True:
        f = try_open_control()
        if f is False:
            if time.monotonic() > deadline:
                raise RuntimeError("the guardian's control pipe stayed busy")
            time.sleep(0.05)
            continue
        return f


def open_control(timeout: float = 60.0):
    """Open the guardian's control pipe; start the guardian once if needed. A start lock keeps two launchers from starting two guardians."""
    deadline = time.monotonic() + timeout
    f = open_existing(deadline)
    if f:
        return f
    lock = k32.CreateMutexW(None, False, f"Local\\DesktopBridgeStart-{INSTANCE}")
    got = False
    try:
        got = k32.WaitForSingleObject(lock, 45000) in (0, 0x80)  # WAIT_OBJECT_0 / WAIT_ABANDONED
        f = open_existing(deadline)  # another launcher may have started it while we waited for the lock
        if f:
            return f
        start_guardian()
        while time.monotonic() < deadline:
            f = try_open_control()
            if f:
                return f
            time.sleep(0.2 if f is None else 0.05)
        raise RuntimeError("the guardian did not come up (control pipe never appeared); see its window or %TEMP%\\desktop-bridge\\worker-<pid>.log")
    finally:
        if got:
            k32.ReleaseMutex(lock)
        k32.CloseHandle(lock)


def request_session(remote: bool = False, bot: str = ""):
    ctl = open_control()
    try:
        req = {"op": "connect", "pid": SELF_PID}
        if remote:
            req["remote"] = True
            req["bot"] = bot or "default"
        ctl.write((json.dumps(req) + "\n").encode())
        buf = b""
        while not buf.endswith(b"\n"):  # blocks while the user answers a first-time 'Allow this client?' prompt in the feed window
            ch = ctl.read(1)
            if not ch:
                break
            buf += ch
        return json.loads(buf.decode() or "{}")
    finally:
        ctl.close()


def open_pipe(path: str, mode: str, deadline: float):
    last = None
    while time.monotonic() < deadline:
        try:
            return open(path, mode, buffering=0)
        except (FileNotFoundError, PermissionError, OSError) as e:
            last = e
        time.sleep(0.1)
    raise RuntimeError(f"could not open {path}: {last}")


def write_all(f, data: bytes) -> None:
    mv = memoryview(data)
    while mv:
        n = f.write(mv)
        mv = mv[n:]


def open_session_pipes(remote: bool = False, bot: str = ""):
    """Ask the guardian for a session and complete the HELLO handshake. Returns (pin, pout)."""
    resp = request_session(remote=remote, bot=bot)
    if not resp.get("ok"):
        raise RuntimeError(resp.get("reason") or "the guardian refused the connection")
    pipe, token = resp["pipe"], resp["token"]
    deadline = time.monotonic() + 40
    pin = open_pipe(r"\\.\pipe" + "\\" + pipe + "-in", "wb", deadline)
    pout = open_pipe(r"\\.\pipe" + "\\" + pipe + "-out", "rb", deadline)
    write_all(pin, f"HELLO {token}\n".encode("ascii"))
    reply = b""
    while not reply.endswith(b"\n") and len(reply) < 16:
        ch = pout.read(1)
        if not ch:
            raise RuntimeError("guardian closed the pipe during the handshake")
        reply += ch
    if reply.strip() != b"OK":
        raise RuntimeError("handshake rejected by the guardian")
    return pin, pout


def run_stdio() -> int:
    try:
        pin, pout = open_session_pipes()
    except Exception as e:
        err(str(e))
        return 1

    def pump_in():
        try:
            while True:
                chunk = sys.stdin.buffer.read1(65536)
                if not chunk:
                    break
                write_all(pin, chunk)
        except Exception:
            pass
        finally:
            try:
                pin.close()
            except Exception:
                pass

    threading.Thread(target=pump_in, daemon=True).start()
    out = sys.stdout.buffer
    try:
        while True:
            data = pout.read(65536)
            if not data:
                break
            out.write(data)
            out.flush()
    except Exception:
        pass
    return 0


def _bot_store():
    from desktop_bridge.remote_auth import BotTokenStore
    return BotTokenStore()


def cmd_add_bot(name: str) -> int:
    store = _bot_store()
    token, created = store.add_bot(name)
    action = "created" if created else "rotated"
    print(f"bot '{name}' {action}")
    print(f"token: {token}")
    print(f"store: {store.path}")
    print("Hand this token to ONE bot only. Revoke with: python launcher.py --revoke-bot " + name)
    return 0


def cmd_list_bots() -> int:
    store = _bot_store()
    bots = store.list_bots()
    if not bots:
        print("no bots yet; create one with: python launcher.py --add-bot <name>")
        print(f"store: {store.path}")
        return 0
    print(f"store: {store.path}")
    for b in bots:
        print(f"  {b['name']:20s}  created={b['created']}  token={b['token_prefix']}")
    return 0


def cmd_revoke_bot(name: str) -> int:
    store = _bot_store()
    if store.revoke_bot(name):
        print(f"revoked bot '{name}'")
        return 0
    print(f"bot '{name}' not found", file=sys.stderr)
    return 1


def run_remote(host: str, port: int) -> int:
    """Serve MCP over streamable-HTTP on loopback; one guardian session per bot token."""
    from desktop_bridge.remote_auth import BotTokenStore
    from desktop_bridge.remote_http import SessionTransport, serve_remote, run_until_stopped

    store = BotTokenStore()
    if not store.list_bots():
        name, token, _ = store.ensure_default("default")
        print(f"[grok-desktop-bridge] no bots configured; created bot '{name}'")
        print(f"[grok-desktop-bridge] token: {token}")
        print(f"[grok-desktop-bridge] store: {store.path}")
    else:
        print(f"[grok-desktop-bridge] bot tokens loaded from {store.path}")
        for b in store.list_bots():
            print(f"[grok-desktop-bridge]   bot={b['name']}  token={b['token_prefix']}")

    stop = threading.Event()
    sessions = {}  # bot -> (pin, pout) keep FDs alive

    def on_log(msg: str) -> None:
        # Visible console (this launcher window) + helpful for tunnel debugging.
        sys.stderr.write(f"[remote] {msg}\n")
        sys.stderr.flush()

    def session_factory(bot: str) -> SessionTransport:
        pin, pout = open_session_pipes(remote=True, bot=bot)
        sessions[bot] = (pin, pout)
        buf = {"leftover": b""}

        def write_bytes(data: bytes) -> None:
            write_all(pin, data)

        def read_line() -> bytes:
            while b"\n" not in buf["leftover"]:
                chunk = pout.read(4096)
                if not chunk:
                    return b""
                buf["leftover"] += chunk
            line, _, rest = buf["leftover"].partition(b"\n")
            buf["leftover"] = rest
            return line + b"\n"

        return SessionTransport(write_bytes, read_line, on_event=on_log, bot=bot)

    print(f"[grok-desktop-bridge] remote mode: http://{host}:{port}/mcp  (loopback only)")
    print("[grok-desktop-bridge] expose with an OUTBOUND tunnel, e.g.:")
    print(f"    cloudflared tunnel --url http://127.0.0.1:{port}")
    print("[grok-desktop-bridge] hand the public HTTPS URL + a bot Bearer token to the cloud bot.")
    print("[grok-desktop-bridge] Esc in the guardian feed stops ALL bots and this HTTP server.")

    httpd = serve_remote(host, port, store, session_factory, on_log=on_log, stop_event=stop)

    def _watch_pipes():
        # Esc stage-2 / feed-window close kills the guardian → pipes drop → stop HTTP for every bot.
        while not stop.wait(0.5):
            dead = False
            for bot, (pin, pout) in list(sessions.items()):
                try:
                    if pin.closed or pout.closed:
                        dead = True
                        break
                except Exception:
                    dead = True
                    break
            # Also: any SessionTransport the HTTP server holds that has closed.
            try:
                for tr in list(httpd._sessions.values()):
                    if tr.closed:
                        dead = True
                        break
            except Exception:
                pass
            if dead:
                on_log("guardian session closed (Esc / feed close) — stopping remote HTTP for all bots")
                stop.set()
                return

    threading.Thread(target=_watch_pipes, name="remote-pipe-watch", daemon=True).start()
    try:
        run_until_stopped(httpd)
    except KeyboardInterrupt:
        stop.set()
        on_log("KeyboardInterrupt — stopping remote HTTP")
    finally:
        stop.set()
        for pin, pout in list(sessions.values()):
            for f in (pin, pout):
                try:
                    f.close()
                except Exception:
                    pass
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Grok Desktop Bridge launcher (stdio MCP or --remote HTTP)")
    ap.add_argument("--remote", action="store_true", help="serve MCP over streamable-HTTP on 127.0.0.1 (Bearer token required)")
    ap.add_argument("--host", default="127.0.0.1", help="remote bind host (loopback only)")
    ap.add_argument("--port", type=int, default=8765, help="remote bind port (default 8765)")
    ap.add_argument("--add-bot", metavar="NAME", help="create/rotate a named bot token and print it")
    ap.add_argument("--list-bots", action="store_true", help="list named bot tokens (prefixes only)")
    ap.add_argument("--revoke-bot", metavar="NAME", help="delete a named bot token")
    args = ap.parse_args(argv)

    if args.add_bot:
        return cmd_add_bot(args.add_bot)
    if args.list_bots:
        return cmd_list_bots()
    if args.revoke_bot:
        return cmd_revoke_bot(args.revoke_bot)
    if args.remote:
        if args.host not in ("127.0.0.1", "localhost", "::1"):
            err("remote mode must bind to loopback only (127.0.0.1)")
            return 2
        try:
            return run_remote(args.host, args.port)
        except Exception as e:
            err(str(e))
            return 1
    return run_stdio()


if __name__ == "__main__":
    sys.exit(main())
