# popup.py -- Spawns terminal popup windows to annoy you into stopping.
# Two types: a quick flash (gentle reminder) and a fullscreen red warning (overtime).

import subprocess
import time

from hotturkey.config import (
    GENTLE_REMINDER_AFTER_SECONDS,
    GENTLE_REMINDER_VISIBLE_SECONDS,
    FIRST_OVERTIME_POPUP_DELAY_SECONDS,
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
    """Open a maximized red terminal window that stays open until the user closes it."""
    cmd = f'mode con cols=120 lines=30 & color 4F & echo. & echo  {message} & echo. & pause'
    # Use cmd directly (no shell=True) and let `start /max` create a maximized
    # console window that waits on `pause` so it cannot disappear on its own.
    subprocess.Popen(
        ["cmd", "/c", "start", "", "/max", "cmd", "/c", cmd],
        creationflags=subprocess.CREATE_NEW_CONSOLE,
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
    - At budget = 0: a fullscreen red warning
    - After that: more fullscreen popups at halving intervals (30, 15, 7.5, 3.75 min...)"""
    now = time.time()

    if not state.is_tracked_activity_running:
        return

    # Gentle flash reminder at the halfway mark
    if (state.seconds_used_this_session >= GENTLE_REMINDER_AFTER_SECONDS
            and not state.has_shown_gentle_reminder):
        state.has_shown_gentle_reminder = True
        used = format_time(state.seconds_used_this_session)
        remaining = format_time(state.remaining_budget_seconds)
        show_flash_popup(f"You've been on for {used}. {remaining} remaining.")

    # Overtime popups once budget hits 0
    if state.remaining_budget_seconds <= 0:
        if state.overtime_escalation_level == 0:
            # First time hitting 0 -- show warning and schedule the next popup
            state.overtime_escalation_level = 1
            state.overtime_next_popup_timestamp = now + FIRST_OVERTIME_POPUP_DELAY_SECONDS
            used = format_time(state.seconds_used_this_session)
            show_fullscreen_popup(f"BUDGET DEPLETED -- You've been on for {used}. Stop now!")

        elif now >= state.overtime_next_popup_timestamp:
            # Time for the next popup -- interval halves each time
            state.overtime_escalation_level += 1
            current_interval = FIRST_OVERTIME_POPUP_DELAY_SECONDS * (
                OVERTIME_INTERVAL_DECAY_FACTOR ** (state.overtime_escalation_level - 1)
            )
            current_interval = max(current_interval, OVERTIME_MIN_INTERVAL_SECONDS)
            state.overtime_next_popup_timestamp = now + current_interval

            used = format_time(state.seconds_used_this_session)
            interval_display = format_time(current_interval)
            show_fullscreen_popup(
                f"STILL GOING -- {used} used. Next popup in {interval_display}!"
            )
