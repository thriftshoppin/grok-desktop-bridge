"""Two-stage Esc. Pure decision logic (unit-tested); the polling loop lives in safety.KillSwitch.

Stage 1 (cancel): Esc while tool calls are running cancels ALL in-flight calls (every client); the bridge stays usable.
Stage 2 (stop):   a second Esc within `window_s` after a cancel, or an Esc while in control with nothing to cancel, stops the bridge
                  (kill state for every client until the user resumes in the feed window).

Esc remains GLOBAL across apps while Grok is in control. The feed window does not need focus, and Esc is not
restricted to the focused window. False trips from Alt+Tab / overlay-show / modifier chords are filtered:
ignore Esc while Alt, Ctrl, or Win is held; swallow the arming tick when in_control becomes true; suppress
edges for a short arm-grace; and suppress edges briefly after Alt/Ctrl/Win is released (a synthetic Esc
often arrives just after the task switcher is dismissed).
"""
from __future__ import annotations


def decide(now: float, inflight: int, last_cancel: float | None, window_s: float) -> str:
    """-> 'cancel' | 'stop'"""
    if last_cancel is not None and now - last_cancel < window_s:
        return "stop"
    if inflight > 0:
        return "cancel"
    return "stop"


def stage(now: float, last_cancel: float | None, window_s: float, killed: bool) -> int:
    """0 = idle, 1 = a cancel happened and a second Esc would stop the bridge, 2 = stopped."""
    if killed:
        return 2
    if last_cancel is not None and now - last_cancel < window_s:
        return 1
    return 0


def should_count_esc_edge(
    *,
    esc_down: bool,
    esc_was_down: bool,
    in_control: bool,
    was_in_control: bool,
    now: float,
    armed_at: float | None,
    arm_grace_s: float,
    alt_down: bool,
    ctrl_down: bool,
    win_down: bool = False,
    modifier_down_prev: bool = False,
    modifier_quiet_until: float | None = None,
    modifier_release_grace_s: float = 0.30,
) -> tuple[bool, bool, float | None, float | None]:
    """Decide whether this poll's Esc rising edge should fire the kill switch.

    Returns (fire, new_esc_was_down, new_armed_at, new_modifier_quiet_until).

    There is no foreground / focus input: a plain Esc in any app counts once the filters below are clear.

    * Only rising edges while in_control.
    * Ignore Esc while Alt, Ctrl, or Win is held (Alt+Tab, Alt+Esc, Ctrl+Esc, Win chords).
    * When in_control arms (False→True), swallow the current Esc state so overlay show cannot fire on that tick.
    * Suppress Esc edges for arm_grace_s after arming.
    * When Alt/Ctrl/Win transitions from down to up, suppress Esc edges until modifier_release_grace_s has passed.
      Held Esc still does not become a new edge after the quiet period; the key must be released and pressed again.
    """
    modifier_down = bool(alt_down or ctrl_down or win_down)
    quiet_until = modifier_quiet_until
    if modifier_down_prev and not modifier_down:
        rel = now + float(modifier_release_grace_s)
        if quiet_until is None or rel > quiet_until:
            quiet_until = rel

    if in_control and not was_in_control:
        # Arming tick: swallow whatever Esc state is present. Only a later up→down counts.
        return False, True, now, quiet_until

    if not in_control:
        return False, bool(esc_down), None, quiet_until

    if armed_at is not None and (now - armed_at) < float(arm_grace_s):
        # Track the physical key so a hold that spans the end of grace is not a new edge.
        return False, bool(esc_down), armed_at, quiet_until

    if quiet_until is not None and now < quiet_until:
        return False, bool(esc_down), armed_at, quiet_until

    rising = bool(esc_down) and not bool(esc_was_down)
    if not rising:
        return False, bool(esc_down), armed_at, quiet_until

    if modifier_down:
        return False, bool(esc_down), armed_at, quiet_until

    return True, bool(esc_down), armed_at, quiet_until
