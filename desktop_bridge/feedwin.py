"""Decisions for the live action feed window.

The feed must stay visible when the user Alt-Tabs or otherwise changes focus, and it must not
become the foreground window to do that. Showing it is SW_SHOWNOACTIVATE (4): visible, not activated.
"""
from __future__ import annotations

# ShowWindow nCmdShow. Do not use SW_SHOW (5) or SW_RESTORE (9): those can activate and steal focus.
SW_SHOWNOACTIVATE = 4
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002


def feed_needs_restore(visible: bool, iconic: bool, on_any_monitor: bool) -> bool:
    """True when the feed is minimized, hidden, or fully off every monitor.

    Focus is not an input. A feed that is visible on a monitor while another app is foreground
    does not need to be touched.
    """
    return bool(iconic) or (not bool(visible)) or (not bool(on_any_monitor))
