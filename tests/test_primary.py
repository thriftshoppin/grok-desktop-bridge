"""The primary client (Grok / Claude desktop) goes first when input is contended."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from desktop_bridge import clients  # noqa: E402


class Primary(unittest.TestCase):
    def test_primary_labels(self):
        self.assertTrue(clients.is_primary("Grok"))
        self.assertTrue(clients.is_primary("Local Computer Assistant"))
        self.assertTrue(clients.is_primary("Claude desktop"))
        self.assertTrue(clients.is_primary("Grok (remote)"))
        self.assertTrue(clients.is_primary("Grok (remote:alice)"))
        self.assertFalse(clients.is_primary("Claude Code (VS Code)"))
        self.assertFalse(clients.is_primary("python.exe selftest.py"))

    def test_grok_label_detection(self):
        self.assertEqual(
            clients.label_for("C:/tools/grok-desktop-bridge/relay.exe"),
            "Grok",
        )
        self.assertEqual(
            clients.label_for("C:/Python/python.exe", "C:/x/grok_relay.py"),
            "Grok",
        )
        self.assertEqual(
            clients.label_for(
                r"C:\Program Files\WindowsApps\Claude_4.1.0.0_x64__x\app\Claude.exe"
            ),
            "Claude desktop",
        )

    def test_hub_counts_only_primary_input_calls(self):
        from desktop_bridge import worker
        h = worker.Hub()
        a = h.add("Claude desktop", "desktop_screenshot")      # primary but not an input tool
        self.assertEqual(h.primary_busy(), 0)
        b = h.add("Claude Code (VS Code)", "desktop_click")    # input, but not primary
        self.assertEqual(h.primary_busy(), 0)
        c = h.add("Claude desktop", "desktop_click")           # primary input
        self.assertEqual(h.primary_busy(), 1)
        d = h.add("Grok", "desktop_type")                      # also primary input
        self.assertEqual(h.primary_busy(), 2)
        h.remove(c)
        h.remove(d)
        self.assertEqual(h.primary_busy(), 0)
        h.remove(a)
        h.remove(b)
        self.assertEqual(h.count(), 0)


if __name__ == "__main__":
    unittest.main()
