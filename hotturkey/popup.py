# popup.py -- Spawns fullscreen red terminal popups when you're in overtime.

import subprocess
from hotturkey.logger import log
from hotturkey.utils import format_duration
from hotturkey.state import overtime_level_from_debt


def show_fullscreen_popup(message):
    # Simple console layout: red background, white text, big-ish window, message, then pause.
    cmd = f"color 4F & mode con cols=120 lines=30 & echo. & echo  {message} & echo. & pause"

    subprocess.Popen(
        ["cmd", "/c", "start", "", "/max", "cmd", "/c", cmd],
    )
    log.info("[POPUP] event=fullscreen message=%s", message)


def check_and_trigger_popups(state):

    is_active = state.is_tracked_activity_running

    # Popups based on how much *overtime* we've accumulated, only start counting once budget is at/below 0.
    if state.remaining_budget_seconds > 0:
        state.overtime_escalation_level = 0
        return

    overtime = getattr(state, "overtime_seconds", 0.0)
    if overtime <= 0:
        state.overtime_escalation_level = 0
        return

    level = overtime_level_from_debt(overtime)
    prev_level = state.overtime_escalation_level
    state.overtime_escalation_level = level

    if not is_active:
        return

    # When we cross into a new level during an active session, fire a popup.
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
