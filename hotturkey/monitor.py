# monitor.py -- The brain of the app.
# Detects if a Steam game or tracked site is focused, then consumes or recovers budget.
# Called every 5 seconds by the monitor loop in run.py.

import psutil
import win32gui
import win32process

import time

from hotturkey.config import (
    STEAM_PROCESS_NAME,
    STEAM_HELPER_PROCESS_NAMES,
    TRACKED_BROWSERS,
    TRACKED_SITES,
    MAX_PLAY_BUDGET_SECONDS,
    BUDGET_RECOVERY_PER_SECOND_IDLE,
)
from hotturkey.logger import log


# --- Detection helpers ---

def get_foreground_window_info():
    """Get the process ID and title of the window the user is currently looking at."""
    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return 0, ""
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    title = win32gui.GetWindowText(hwnd)
    return pid, title


def is_steam_ancestor(pid):
    """Walk up the process tree from a given PID to check if steam.exe is a parent.
    This catches games launched through intermediate launchers (e.g. publisher launchers
    like PioneerGame.exe that then launch the actual game)."""
    try:
        proc = psutil.Process(pid)
        for _ in range(10):
            if proc.name().lower() == STEAM_PROCESS_NAME:
                return True
            proc = proc.parent()
            if proc is None:
                break
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return False


def detect_steam_game_focused(foreground_pid):
    """Check if the currently focused window is a Steam game.
    Works by checking if the focused process has steam.exe as an ancestor,
    and that it's not one of Steam's own helper processes."""
    if foreground_pid == 0:
        return ""
    try:
        proc = psutil.Process(foreground_pid)
        proc_name = proc.name().lower()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return ""

    # Ignore Steam's own background processes
    if proc_name in STEAM_HELPER_PROCESS_NAMES:
        return ""

    if is_steam_ancestor(foreground_pid):
        return proc.name()

    return ""


def detect_tracked_site_focused(foreground_title):
    """Check if the focused window is a tracked site (e.g. YouTube) in a tracked browser.
    Looks for both a site name and a browser name in the window title.
    Returns a label like 'YouTube (Brave)' or empty string if no match."""
    title_lower = foreground_title.lower()
    for site in TRACKED_SITES:
        if site in title_lower:
            for browser in TRACKED_BROWSERS:
                if browser in title_lower:
                    return f"{site.title()} ({browser.title()})"
    return ""


def detect_tracked_activity():
    """The main detection function. Checks the focused window against all detectors.
    Returns (is_active, source_name) where source_name is a human-readable label."""
    foreground_pid, foreground_title = get_foreground_window_info()

    steam_game_name = detect_steam_game_focused(foreground_pid)
    if steam_game_name:
        log.info(f"[GAMING] {steam_game_name} is focused")
        return True, f"Steam: {steam_game_name}"

    browser_match = detect_tracked_site_focused(foreground_title)
    if browser_match:
        log.info(f"[WATCHING] {browser_match} is focused")
        return True, browser_match

    log.debug("[IDLE] No tracked activity focused")
    return False, ""


# --- Budget logic ---

def consume_budget(state, elapsed_seconds):
    """Subtract play time from budget. Budget stops at 0, never goes negative."""
    before = state.remaining_budget_seconds
    state.remaining_budget_seconds = max(0.0, state.remaining_budget_seconds - elapsed_seconds)
    spent = before - state.remaining_budget_seconds
    if spent > 0:
        log.info(f"[BUDGET] -{spent:.1f}s consumed, {state.remaining_budget_seconds:.0f}s remaining")


def recover_budget(state, elapsed_seconds):
    """Add time back to budget while idle. Caps at the normal 1hr max,
    unless extra time from the CLI has pushed the budget above that."""
    cap = max(MAX_PLAY_BUDGET_SECONDS, state.remaining_budget_seconds)
    recovered = elapsed_seconds * BUDGET_RECOVERY_PER_SECOND_IDLE
    before = state.remaining_budget_seconds
    state.remaining_budget_seconds = min(cap, state.remaining_budget_seconds + recovered)
    gained = state.remaining_budget_seconds - before
    if gained > 0.01:
        log.info(f"[BUDGET] +{gained:.1f}s recovered, {state.remaining_budget_seconds:.0f}s remaining")


def apply_pending_extra_time(state):
    """Check if the user ran 'hotturkey extra X' and pick up the extra minutes.
    Converts minutes to seconds and adds them to the budget."""
    if state.extra_minutes_pending_from_cli > 0:
        extra_seconds = state.extra_minutes_pending_from_cli * 60
        state.remaining_budget_seconds += extra_seconds
        log.info(f"[EXTRA] +{state.extra_minutes_pending_from_cli:.0f}min added, "
                 f"{state.remaining_budget_seconds:.0f}s remaining")
        state.extra_minutes_pending_from_cli = 0.0


# --- Main update function ---

def update_budget(state):
    """Called every poll cycle by run.py. This is where everything comes together:
    1. Calculate how much time passed since last check
    2. Pick up any extra time from the CLI
    3. Detect if a game or tracked site is focused
    4. If active: start/continue session, subtract from budget
    5. If idle: end session, recover budget"""
    now = time.time()
    elapsed_seconds = now - state.last_poll_timestamp
    state.last_poll_timestamp = now

    apply_pending_extra_time(state)

    is_active, source_name = detect_tracked_activity()

    if is_active:
        # Start a new session if this is the first detection
        if not state.is_tracked_activity_running:
            log.info(f"[SESSION] Started: {source_name}")
            state.current_session_start_timestamp = now
            state.seconds_used_this_session = 0.0
            state.has_shown_gentle_reminder = False

        state.is_tracked_activity_running = True
        state.tracked_activity_name = source_name
        state.seconds_used_this_session += elapsed_seconds
        consume_budget(state, elapsed_seconds)
    else:
        # End the session and reset overtime if we were previously active
        if state.is_tracked_activity_running:
            log.info(f"[SESSION] Ended: {state.tracked_activity_name} "
                     f"(used {state.seconds_used_this_session:.0f}s)")
            state.overtime_escalation_level = 0
            state.overtime_next_popup_timestamp = 0.0

        state.is_tracked_activity_running = False
        state.tracked_activity_name = ""
        recover_budget(state, elapsed_seconds)

    return is_active, source_name
