# popup.py -- Spawns terminal popup windows to annoy you into stopping.
# Two types: a quick flash (gentle reminder) and a fullscreen red warning (overtime).

import subprocess
import time

from hotturkey.config import (
    GENTLE_REMINDER_AFTER_SECONDS,
    GENTLE_REMINDER_VISIBLE_SECONDS,
    MAX_PLAY_BUDGET_SECONDS,
    OVERTIME_INTERVAL_DECAY_FACTOR,
    OVERTIME_MIN_INTERVAL_SECONDS,
)
from hotturkey.logger import log


def show_flash_popup(message):
    """Open a small terminal window that shows a message and auto-closes after a few seconds."""
    timeout = GENTLE_REMINDER_VISIBLE_SECONDS
    cmd = f'echo. & echo  {message} & echo. & timeout /t {timeout} /nobreak >nul'
    subprocess.Popen(
        ["cmd", "/c", cmd],
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )
    log.info(f"[POPUP] Flash: {message}")


def show_fullscreen_popup(message):
    """Open a maximized red terminal window that stays open until the user presses a key.

    Implemented via a single `cmd` window started maximized. After showing the
    message, it runs `pause`, so pressing Enter (or any key) closes the window.
    """
    # Simple console layout: red background, white text, big-ish window, message, then pause.
    cmd = f"color 4F & mode con cols=120 lines=30 & echo. & echo  {message} & echo. & pause"

    # Use `start` to spawn one maximized console window. Because the main app is
    # running detached in the background, this will be the only visible window.
    subprocess.Popen(
        ["cmd", "/c", "start", "", "/max", "cmd", "/c", cmd],
    )
    log.info(f"[POPUP] Fullscreen: {message}")


def format_time(seconds):
    """Turn a number of seconds into a mm:ss string (e.g. 1800 -> '30:00')."""
    minutes = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{minutes}:{secs:02d}"


def check_and_trigger_popups(state):
    """Called every poll cycle. Decides if a popup should appear right now:
    - At 30 min used: a quick flash reminder (once per session)
    - In overtime: fullscreen warnings based on how much *overtime* you've gone:
        * Level 1  at 50% of your budget in overtime  (e.g. 30 min extra on a 60 min budget)
        * Level 2  after half of that again          (e.g. +15 min more)
        * Level 3  after half again, and so on."""
    now = time.time()

    is_active = state.is_tracked_activity_running

    # Gentle flash reminder at the halfway mark
    if (state.seconds_used_this_session >= GENTLE_REMINDER_AFTER_SECONDS
            and not state.has_shown_gentle_reminder):
        state.has_shown_gentle_reminder = True
        used = format_time(state.seconds_used_this_session)
        remaining = format_time(state.remaining_budget_seconds)
        show_flash_popup(f"You've been on for {used}. {remaining} remaining.")

    # Overtime popups based on how much *overtime* we've accumulated.
    # We only start counting once budget is at/below 0.
    if state.remaining_budget_seconds > 0:
        # Not yet in overtime.
        state.overtime_escalation_level = 0
        return

    overtime = getattr(state, "overtime_seconds", 0.0)
    if overtime <= 0:
        state.overtime_escalation_level = 0
        return

    # Base overtime interval is 50% of the budget, but never less than the
    # configured minimum interval. For a 60 min budget, this is 30 min.
    base_interval = max(
        float(OVERTIME_MIN_INTERVAL_SECONDS),
        0.5 * float(MAX_PLAY_BUDGET_SECONDS),
    )

    # Determine which overtime "level" we're currently in:
    #   - Level 1: any overtime > 0 (just hit budget 0)
    #   - Level 2: >= base_interval overtime (50% over budget)
    #   - Level 3: >= base_interval + base_interval*0.5 (75% over budget), etc.
    level = 1  # we've already confirmed overtime > 0

    remaining = overtime
    # First chunk corresponds to Level 2 threshold.
    remaining_for_higher = max(0.0, remaining - base_interval)

    if remaining_for_higher > 0:
        level = 2
        interval = base_interval * OVERTIME_INTERVAL_DECAY_FACTOR

        while remaining_for_higher >= interval and interval >= 1.0:
            remaining_for_higher -= interval
            level += 1
            interval *= OVERTIME_INTERVAL_DECAY_FACTOR
            if interval < 1.0:
                break

    prev_level = state.overtime_escalation_level

    # Always keep the stored level in sync with the current overtime amount,
    # even when no tracked activity is running, so the UI and future popups
    # reflect the unlocked level.
    state.overtime_escalation_level = level

    # If we aren't actively tracking (no game/site focused), we don't show
    # popups, but we still updated the level above.
    if not is_active:
        return

    # When we cross into a *new* level during an active session, fire a popup.
    if level > prev_level:
        used = format_time(state.seconds_used_this_session)

        if level == 1:
            show_fullscreen_popup(
                f"BUDGET DEPLETED -- You've been on for {used}. "
                f"Overtime L1 reached (budget exhausted). Stop now!"
            )
        else:
            show_fullscreen_popup(
                f"STILL GOING -- {used} used. "
                f"Overtime L{level} reached. Stop now!"
            )
