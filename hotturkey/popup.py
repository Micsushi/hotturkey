# popup.py -- Spawns fullscreen red terminal popups when you're in overtime.

import subprocess
from hotturkey.logger import log
from hotturkey.utils import format_duration
from hotturkey.state import overtime_level_from_debt


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
    log.info("[POPUP] event=fullscreen message=%s", message)


def check_and_trigger_popups(state):
    """Called every poll cycle. In overtime, show fullscreen warnings by level:
    L1 at budget 0, L2 at 50% of budget in overtime, L3+ at halved steps."""
    is_active = state.is_tracked_activity_running

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

    # Compute overtime level using shared helper.
    level = overtime_level_from_debt(overtime)

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
        used = format_duration(state.seconds_used_this_session)

        if level == 1:
            show_fullscreen_popup(
                f"BUDGET DEPLETED -- You've been on for {used}. "
                f"Overtime L1 reached (budget exhausted). Stop now!"
            )
        else:
            show_fullscreen_popup(
                f"STILL GOING -- {used} used. " f"Overtime L{level} reached. Stop now!"
            )
