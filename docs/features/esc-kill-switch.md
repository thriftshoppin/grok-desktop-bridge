# Feature: two-stage Esc and kill switch

Esc (polled every 25 ms only while Grok is in control; no hook) is **global across apps** — the feed console does **not** need focus, and Esc is not limited to the focused window. First press cancels the in-flight calls of every client (`CANCELLED_BY_USER`, yellow border); a second press within 10 s stops the bridge (red border, `KILL_SWITCH` everywhere until the user resumes). `Ctrl+Alt+Pause` and `Ctrl+Alt+Shift+K` stop it directly.

## False-trip filters (Alt+Tab / focus changes)

Remote tool calls arm `in_control` and show the overlay. That can interrupt Alt+Tab and synthesize Esc. Filters, without disabling Esc:

* Ignore Esc while **Alt**, **Ctrl**, or **Win** is held (Alt+Tab / Alt+Esc / Ctrl+Esc).
* When `in_control` rises False→True, swallow the current Esc state and suppress edges for `kill_switch.esc_arm_grace_s` (default **0.35 s**).
* After Alt/Ctrl/Win is released, suppress edges for `kill_switch.esc_modifier_release_grace_s` (default **0.30 s**). A key that is still held when the quiet period ends does not count; it has to be released and pressed again.
* The feed window is shown and restored with `SW_SHOWNOACTIVATE`, so it stays visible across focus changes without becoming the foreground window. `feed.always_on_top` is **false** by default.

Known limit: the bridge's own injected Esc still suppresses real Esc for 120 ms (audit DB-7). Tests: `tests/test_guardian.py` (decisions and edge filter). A physical keypress is confirmed by the user by hand.
