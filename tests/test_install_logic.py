"""Cleanup boundaries, process identity, startup rollback, Esc-adjacent install rules."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from desktop_bridge import feedwin, install_logic as L  # noqa: E402

GROK_BRAND = 'PRODUCT = "GrokDesktopBridge"\nSERVER_NAME = "grok-desktop-bridge"\n'
OTHER_BRAND = 'SERVER_NAME = "desktop-mcp-bridge"\n'
BOTH_BRAND = 'PRODUCT = "GrokDesktopBridge"\nSERVER_NAME = "desktop-mcp-bridge"\n'
ROOT = r"C:\Users\SysAdmin\grok-desktop-bridge"


def dir_node(path, name, brand="", children=None, reparse=False):
    return {
        "path": path, "name": name, "is_dir": True, "is_reparse": reparse,
        "brand_text": brand, "children": children or [],
    }


def file_node(path, name, target=None):
    return {
        "path": path, "name": name, "is_dir": False, "is_reparse": False,
        "target_path": target, "children": [],
    }


class Names(unittest.TestCase):
    def test_numbered_and_nested_names(self):
        for name in (
            "grok-desktop-bridge",
            "grok-desktop-bridge-main",
            "grok-desktop-bridge-main (1)",
            "grok-desktop-bridge-main(2)",
            "grok-desktop-bridge (3)",
            "grok-desktop-bridge-main-4",
            "desktop-mcp-bridge",
            "desktop-mcp-bridge-main",
            "desktop-mcp-bridge-main (12)",
        ):
            self.assertTrue(L.folder_name_matches(name), name)

    def test_does_not_wildcard_unrelated_names(self):
        for name in (
            "grok-desktop-bridge-backup",
            "my-grok-desktop-bridge",
            "not-the-bridge",
            "GrokDesktopBridge-logs",
            "claude-desktop-bridge",
        ):
            self.assertFalse(L.folder_name_matches(name), name)


class Classify(unittest.TestCase):
    def test_repo_brand_is_grok_even_though_the_docstring_mentions_the_other_bridge(self):
        brand_path = os.path.join(os.path.dirname(__file__), "..", "desktop_bridge", "brand.py")
        text = open(brand_path, encoding="utf-8").read()
        self.assertEqual(L.classify_dir("grok-desktop-bridge-main", text), "grok")
        self.assertEqual(L.classify_dir("desktop-mcp-bridge", text), "grok")

    def test_other_client_name_without_grok_brand_is_not_a_default_wipe(self):
        self.assertEqual(L.classify_dir("desktop-mcp-bridge", ""), "other-client")
        self.assertEqual(L.classify_dir("desktop-mcp-bridge-main (1)", OTHER_BRAND), "other-client")

    def test_both_products_are_ambiguous(self):
        self.assertEqual(L.classify_dir("grok-desktop-bridge", BOTH_BRAND), "ambiguous")

    def test_other_brand_in_a_grok_named_folder_is_not_silently_grok(self):
        self.assertEqual(L.classify_dir("grok-desktop-bridge-main", OTHER_BRAND), "other-client")

    def test_scripts_and_shortcut(self):
        self.assertEqual(L.classify_file("Apply-EscFix.ps1"), "grok-script")
        self.assertEqual(L.classify_file("GrokBridge-LightSwitch.cmd"), "grok-script")
        self.assertEqual(L.classify_file("Update-GrokBridgeInPlace.ps1"), "grok-script")
        self.assertEqual(L.classify_file("notes.txt"), "ignore")
        self.assertEqual(L.classify_shortcut("Grok Desktop Bridge Light Switch.lnk", ROOT + r"\GrokBridge-LightSwitch.cmd"), "grok-shortcut")
        self.assertEqual(
            L.classify_shortcut("Grok Desktop Bridge Light Switch.lnk", r"C:\tools\desktop-mcp-bridge\run.cmd"),
            "ambiguous",
        )


class CleanupPlan(unittest.TestCase):
    def test_reparse_is_not_entered_or_deleted(self):
        tree = [dir_node(r"C:\Users\SysAdmin\Downloads\grok-desktop-bridge", "grok-desktop-bridge", reparse=True, children=[
            dir_node(r"D:\secret\grok-desktop-bridge-main", "grok-desktop-bridge-main", brand=GROK_BRAND),
        ])]
        plan = L.build_cleanup_plan(tree, protected_roots=[])
        paths = [p["path"] for p in plan]
        self.assertIn(r"C:\Users\SysAdmin\Downloads\grok-desktop-bridge", paths)
        self.assertNotIn(r"D:\secret\grok-desktop-bridge-main", paths)
        self.assertEqual(plan[0]["class"], "skip-reparse")
        self.assertEqual(plan[0]["action"], "skip")
        self.assertFalse(any(p["action"] == "remove" for p in plan))

    def test_nested_extract_and_numbered_copy_and_draft_script(self):
        tree = [
            dir_node(r"C:\dl\grok-desktop-bridge-main", "grok-desktop-bridge-main", brand=GROK_BRAND, children=[
                dir_node(r"C:\dl\grok-desktop-bridge-main\grok-desktop-bridge-main", "grok-desktop-bridge-main", brand=GROK_BRAND),
                file_node(r"C:\dl\grok-desktop-bridge-main\Apply-EscFix.ps1", "Apply-EscFix.ps1"),
            ]),
            dir_node(r"C:\dl\grok-desktop-bridge-main (1)", "grok-desktop-bridge-main (1)", brand=""),
            file_node(r"C:\dl\GrokBridge-LightSwitch.ps1", "GrokBridge-LightSwitch.ps1"),
            dir_node(r"C:\dl\desktop-mcp-bridge", "desktop-mcp-bridge", brand=OTHER_BRAND, children=[
                file_node(r"C:\dl\desktop-mcp-bridge\keep.txt", "keep.txt"),
            ]),
            dir_node(r"C:\dl\unrelated", "unrelated", children=[
                file_node(r"C:\dl\unrelated\python.txt", "python.txt"),
            ]),
        ]
        plan = L.build_cleanup_plan(tree, protected_roots=[r"C:\dl\grok-desktop-bridge-src"])
        remove = [p["path"] for p in plan if p["action"] == "remove"]
        self.assertIn(r"C:\dl\grok-desktop-bridge-main", remove)
        self.assertIn(r"C:\dl\grok-desktop-bridge-main (1)", remove)
        self.assertIn(r"C:\dl\GrokBridge-LightSwitch.ps1", remove)
        self.assertNotIn(r"C:\dl\grok-desktop-bridge-main\grok-desktop-bridge-main", remove)
        self.assertNotIn(r"C:\dl\grok-desktop-bridge-main\Apply-EscFix.ps1", remove)
        self.assertTrue(all("desktop-mcp-bridge" not in p or p.endswith("GrokBridge-LightSwitch.ps1") for p in remove))
        other = [p for p in plan if p["class"] == "other-client"]
        self.assertEqual(other[0]["action"], "skip")
        self.assertTrue(L.confirmation_ok(L.CONFIRM_GROK, plan))
        self.assertFalse(L.confirmation_ok("yes", plan))

    def test_other_client_requires_explicit_path_and_the_longer_phrase(self):
        tree = [dir_node(r"C:\dl\desktop-mcp-bridge", "desktop-mcp-bridge", brand=OTHER_BRAND)]
        plan = L.build_cleanup_plan(tree, protected_roots=[], include_other_paths=[r"C:\dl\desktop-mcp-bridge"])
        self.assertEqual(plan[0]["action"], "remove")
        self.assertFalse(L.confirmation_ok(L.CONFIRM_GROK, plan))
        self.assertTrue(L.confirmation_ok(L.CONFIRM_OTHER, plan))

    def test_running_package_is_protected(self):
        pkg = r"C:\Users\SysAdmin\Downloads\grok-desktop-bridge-fresh\grok-desktop-bridge"
        tree = [dir_node(pkg, "grok-desktop-bridge", brand=GROK_BRAND, children=[
            file_node(pkg + r"\Install-GrokBridge.ps1", "Install-GrokBridge.ps1"),
        ])]
        plan = L.build_cleanup_plan(tree, protected_roots=[pkg])
        self.assertTrue(plan)
        self.assertTrue(all(p["action"] == "skip" and p["class"] == "protected" for p in plan))

    def test_depth_limit_does_not_walk_the_disk(self):
        # depth 7 match is not visited when max depth is 6
        node = dir_node(r"C:\dl\grok-desktop-bridge", "grok-desktop-bridge", brand=GROK_BRAND)
        cursor = node
        for i in range(7):
            child = dir_node(cursor["path"] + r"\grok-desktop-bridge", "grok-desktop-bridge", brand=GROK_BRAND)
            cursor["children"] = [child]
            cursor = child
        seen = L.walk_tree([node], max_depth=6)
        self.assertLessEqual(len(seen), 6)
        self.assertNotIn(cursor["path"], [n["path"] for n in seen])

    def test_explicit_token_store_is_listed_and_unrelated_state_is_absent(self):
        plan = L.build_cleanup_plan([], protected_roots=[], explicit_targets=[
            {"path": r"C:\Users\SysAdmin\AppData\Local\GrokDesktopBridge", "class": "token-store",
             "reason": "TOKEN SCOPE (contents are not printed)", "exists": True},
            {"path": r"C:\ProgramData\DesktopBridge", "class": "state", "exists": False},
        ])
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]["class"], "token-store")
        self.assertEqual(plan[0]["action"], "remove")
        self.assertNotIn("token", plan[0]["path"].lower())


class PythonSupport(unittest.TestCase):
    def test_supported_set_is_64_bit_3_12_through_3_14(self):
        for minor in (12, 13, 14):
            got = L.assess_python((3, minor, 0), 64, "CPython")
            self.assertTrue(got["ok"], got)
        for spec in (
            ((3, 14), 32, "CPython"),
            ((3, 11), 64, "CPython"),
            ((3, 10), 64, "CPython"),
            ((3, 15), 64, "CPython"),
            ((3, 14), 64, "PyPy"),
        ):
            got = L.assess_python(spec[0], spec[1], spec[2])
            self.assertFalse(got["ok"], spec)
            self.assertIn("3.14", got["reason"])


class SecretsAndProcesses(unittest.TestCase):
    def test_redact_keeps_tunnel_url_and_drops_bearer(self):
        raw = "\n".join([
            "token: super-secret-token-value",
            "Authorization: Bearer abcdefghijklmnop",
            "https://lucky-river.trycloudflare.com",
            "Authorization: Bearer <bot-token>",
        ])
        out = L.redact_text(raw)
        self.assertNotIn("super-secret-token-value", out)
        self.assertNotIn("abcdefghijklmnop", out)
        self.assertIn("https://lucky-river.trycloudflare.com", out)
        self.assertIn("<bot-token>", out)

    def test_owned_processes_are_narrow(self):
        py = ROOT + r"\.venv\Scripts\python.exe"
        self.assertTrue(L.is_owned_grok_process(py + " launcher.py --remote --port 8790", py, ROOT, 8790))
        self.assertTrue(L.is_owned_grok_process(
            py + " -m desktop_bridge.worker --guardian --instance grok", py, ROOT, 8790))
        self.assertFalse(L.is_owned_grok_process(
            py + " -m desktop_bridge.worker --guardian --instance main", py, ROOT, 8790))
        self.assertFalse(L.is_owned_grok_process(
            r"C:\Python\python.exe launcher.py --remote", r"C:\Python\python.exe", ROOT, 8790))
        self.assertTrue(L.is_owned_grok_process(
            "cloudflared tunnel --url http://127.0.0.1:8790", r"C:\Tools\cloudflared.exe", ROOT, 8790))
        self.assertFalse(L.is_owned_grok_process(
            "cloudflared tunnel --url http://127.0.0.1:8080", r"C:\Tools\cloudflared.exe", ROOT, 8790))
        self.assertFalse(L.is_owned_grok_process("node server.js", ROOT + r"\node.exe", ROOT, 8790))

    def test_pid_reuse_is_not_stopped(self):
        recorded = {"pid": 42, "creation": "100", "image": r"C:\py.exe"}
        reused = {"pid": 42, "creation": "999", "image": r"C:\py.exe"}
        same = {"pid": 42, "creation": "100", "image": r"C:\py.exe"}
        ok, why = L.safe_to_stop(recorded, reused)
        self.assertFalse(ok)
        self.assertEqual(why, "pid-reused")
        ok, why = L.safe_to_stop(recorded, same)
        self.assertTrue(ok)
        self.assertEqual(L.rollback_pids([recorded], {42: reused}), [])
        self.assertEqual(L.rollback_pids([recorded], {42: same}), [42])

    def test_uac_cancel_does_not_fall_through_to_the_task(self):
        self.assertEqual(L.runas_failure_action(1223), "abort")
        self.assertEqual(L.runas_failure_action(5), "try-scheduled-task")


class Startup(unittest.TestCase):
    def test_ready_requires_guardian_http_401_and_tunnel(self):
        got = L.classify_startup(
            launcher_exit=None, log_text="remote MCP listening", http_status=401,
            guardian_owned=True, tunnel_url="https://lucky-river.trycloudflare.com", timed_out=False,
        )
        self.assertEqual(got["state"], "ready")
        self.assertFalse(got["rollback"])

    def test_spawn_alone_is_not_ready(self):
        got = L.classify_startup(
            launcher_exit=None, log_text="", http_status=None,
            guardian_owned=False, tunnel_url=None, timed_out=False,
        )
        self.assertEqual(got["state"], "wait")

    def test_uac_cancel_rolls_back(self):
        got = L.classify_startup(
            launcher_exit=1, log_text="UAC was cancelled (error 1223). The scheduled-task fallback was not used.",
            http_status=None, guardian_owned=False, tunnel_url=None, timed_out=False,
        )
        self.assertEqual(got["state"], "uac_cancelled")
        self.assertTrue(got["rollback"])

    def test_timeout_and_early_exit_roll_back(self):
        got = L.classify_startup(
            launcher_exit=None, log_text="", http_status=401,
            guardian_owned=True, tunnel_url=None, timed_out=True,
        )
        self.assertEqual(got["state"], "failed")
        self.assertTrue(got["rollback"])
        got = L.classify_startup(
            launcher_exit=1, log_text="boom", http_status=None,
            guardian_owned=False, tunnel_url=None, timed_out=False,
        )
        self.assertEqual(got["state"], "failed")
        self.assertTrue(got["rollback"])


class FeedAndOverlay(unittest.TestCase):
    def test_feed_restore_does_not_depend_on_focus(self):
        self.assertFalse(feedwin.feed_needs_restore(True, False, True))
        self.assertTrue(feedwin.feed_needs_restore(False, False, True))
        self.assertTrue(feedwin.feed_needs_restore(True, True, True))
        self.assertTrue(feedwin.feed_needs_restore(True, False, False))
        self.assertEqual(feedwin.SW_SHOWNOACTIVATE, 4)

    def test_overlay_label_is_exact(self):
        path = os.path.join(os.path.dirname(__file__), "..", "desktop_bridge", "overlay.py")
        text = open(path, encoding="utf-8").read()
        self.assertIn('"Grok is using your computer. Press Esc to Stop"', text)


if __name__ == "__main__":
    unittest.main()
