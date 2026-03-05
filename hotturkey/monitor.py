# monitor.py -- The brain of the app.
# Detects if a Steam game or tracked site is focused, then consumes or recovers budget.
# Called every 5 seconds by the monitor loop in run.py.

import psutil
import win32gui
import win32process

import ctypes
import ctypes.wintypes as wintypes
import time

from hotturkey.config import (
    STEAM_PROCESS_NAME,
    STEAM_HELPER_PROCESS_NAMES,
    TRACKED_BROWSERS,
    TRACKED_SITES,
    MAX_PLAY_BUDGET_SECONDS,
    BUDGET_RECOVERY_PER_SECOND_IDLE,
    DETECTION_POLL_INTERVAL_SECONDS,
    BONUS_SITES,
    BONUS_RECOVERY_MULTIPLIER,
    AFK_IDLE_THRESHOLD_SECONDS,
)
from hotturkey.logger import log
from hotturkey.state import load_extra_minutes_pending, save_extra_minutes_pending


# --- Detection helpers ---

# Names of executables we've positively identified as Steam-launched games.
# Once something has been seen as a Steam game, we keep treating that exe name
# as a game for the rest of the session, and persist it across runs via
# AppState.known_steam_game_exes.
_KNOWN_STEAM_GAME_NAMES = set()

# Width (in characters) of the ASCII budget bar shown in [BUDGET] logs.
_BUDGET_BAR_WIDTH = 16

# Track AFK state so we can log transitions cleanly.
_was_afk = False

# Ensure we only hydrate _KNOWN_STEAM_GAME_NAMES from state once.
_steam_known_initialized = False

# Throttle how often we scan for new Steam game executables. The scan is now
# limited to Steam's own child processes (much cheaper than walking every
# process and its ancestors), so we can keep this interval relatively short.
_STEAM_REFRESH_INTERVAL_SECONDS = 5.0
_last_steam_refresh_time = 0.0


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwTime", wintypes.DWORD),
    ]


_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32


def get_idle_seconds() -> float:
    """Return the number of seconds since the last keyboard or mouse input.

    Uses the Windows GetLastInputInfo API.
    """
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not _user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    millis_since_input = _kernel32.GetTickCount() - info.dwTime
    return max(0.0, millis_since_input / 1000.0)

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


def refresh_known_steam_games(state):
    """Discover new Steam game executables by looking only at Steam's children.

    Instead of walking every process on the system and asking "does this have
    steam.exe as an ancestor?", we:
      1) Find steam.exe processes
      2) Walk their child processes recursively
      3) Treat any non-helper executables we see as candidate games

    This is equivalent in effect to "polling whenever a new process under Steam
    appears", but implemented with a lightweight periodic scan."""
    try:
        steam_procs = []
        for proc in psutil.process_iter(["pid", "name"]):
            name = proc.info.get("name") or ""
            if not name:
                continue
            if name.lower() == STEAM_PROCESS_NAME:
                steam_procs.append(proc)

        if not steam_procs:
            return

        for steam_proc in steam_procs:
            try:
                children = steam_proc.children(recursive=True)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.Error):
                continue

            for child in children:
                try:
                    name = child.name()
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.Error):
                    continue

                if not name:
                    continue

                lname = name.lower()
                # Skip helpers and ones we already know about.
                if lname in STEAM_HELPER_PROCESS_NAMES or lname in _KNOWN_STEAM_GAME_NAMES:
                    continue

                _KNOWN_STEAM_GAME_NAMES.add(lname)
                if lname not in (ex.lower() for ex in state.known_steam_game_exes):
                    state.known_steam_game_exes.append(lname)
                log.info(f"[GAMING] Learned Steam game exe: {name}")
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.Error):
        # Best-effort only; failures here shouldn't break the main loop.
        pass


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

    # If we've already confirmed this exe as a Steam game earlier in the
    # session, keep treating it as a game even if its current process tree
    # no longer has steam.exe as an ancestor (some launchers/anti-cheat
    # chains re-parent the actual game process).
    if proc_name in _KNOWN_STEAM_GAME_NAMES:
        return proc.name()

    # First-time detection: walk up the process tree to see if steam.exe is
    # an ancestor. If so, remember this exe name as a known Steam game.
    if is_steam_ancestor(foreground_pid):
        _KNOWN_STEAM_GAME_NAMES.add(proc_name)
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


def detect_bonus_site_focused(foreground_title):
    """Check if the focused window is a 'bonus' (productive) site.
    Returns a simple label like 'Leetcode' or empty string if no match."""
    title_lower = foreground_title.lower()
    for site in BONUS_SITES:
        if site in title_lower:
            # Capitalize the keyword for display (e.g. 'leetcode' -> 'Leetcode').
            return site.replace("-", " ").title()
    return ""


def detect_tracked_activity():
    """The main detection function. Checks the focused window against all detectors.
    Returns (mode, source_name) where mode is one of:
      - 'consume' : tracked entertainment (Steam / tracked sites)
      - 'bonus'   : productive / bonus sites (faster recovery)
      - 'idle'    : nothing relevant focused
    """
    foreground_pid, foreground_title = get_foreground_window_info()

    # Bonus / productive sites first: we don't want to consume budget here.
    bonus_label = detect_bonus_site_focused(foreground_title)
    if bonus_label:
        log.info(f"[BONUS] {bonus_label} is focused")
        return "bonus", bonus_label

    steam_game_name = detect_steam_game_focused(foreground_pid)
    if steam_game_name:
        log.info(f"[GAMING] {steam_game_name} is focused")
        return "consume", f"Steam: {steam_game_name}"

    browser_match = detect_tracked_site_focused(foreground_title)
    if browser_match:
        log.info(f"[WATCHING] {browser_match} is focused")
        return "consume", browser_match

    log.debug("[IDLE] No tracked activity focused")
    return "idle", ""


# --- Budget logic ---

def _format_mmss(seconds: float) -> str:
    """Format a number of seconds as MM:SS (e.g. 924 -> '15:24')."""
    total = max(0, int(seconds))
    minutes = total // 60
    secs = total % 60
    return f"{minutes}:{secs:02d}"


def _format_budget_bar(state, is_recovering: bool) -> str:
    """Return an ASCII bar representing how much of the budget is used.

    Example: [██████░░░░░░░░] 25% used (recovering)
             [████████████████] 100% used (overtime L2)
    """
    cap = float(MAX_PLAY_BUDGET_SECONDS) if MAX_PLAY_BUDGET_SECONDS > 0 else 1.0
    remaining_clamped = max(0.0, min(state.remaining_budget_seconds, cap))
    used_ratio = 1.0 - (remaining_clamped / cap)
    used_ratio = max(0.0, min(1.0, used_ratio))

    used_blocks = int(round(used_ratio * _BUDGET_BAR_WIDTH))
    used_blocks = max(0, min(_BUDGET_BAR_WIDTH, used_blocks))

    # Use plain ASCII characters so logs work on all Windows encodings.
    # '#' = used time, '-' = remaining time.
    bar = "#" * used_blocks + "-" * (_BUDGET_BAR_WIDTH - used_blocks)
    percent = int(round(used_ratio * 100))

    # Suffix describing state: overtime vs recovering vs full/normal.
    suffix_parts = []
    if state.remaining_budget_seconds <= 0:
        # We are in overtime; escalation level 0 means we've just hit 0 for
        # the first time and the first popup is about to be scheduled.
        level = state.overtime_escalation_level or 1
        suffix_parts.append(f"overtime L{level}")
    elif is_recovering:
        if percent == 0:
            suffix_parts.append("full")
        else:
            suffix_parts.append("recovering")

    suffix = ""
    if suffix_parts:
        suffix = " (" + ", ".join(suffix_parts) + ")"

    return f"[{bar}] {percent:3d}% used{suffix}"

def consume_budget(state, elapsed_seconds):
    """Subtract play time from budget. Budget stops at 0, never goes negative."""
    before = state.remaining_budget_seconds
    state.remaining_budget_seconds = max(0.0, state.remaining_budget_seconds - elapsed_seconds)
    spent = before - state.remaining_budget_seconds
    bar = _format_budget_bar(state, is_recovering=False)
    remaining_str = _format_mmss(state.remaining_budget_seconds)
    log.info(
        f"[BUDGET] | -{spent:.1f}s consumed | "
        f"{remaining_str} remaining | {bar}"
    )


def recover_budget(state, elapsed_seconds):
    """Add time back to budget while idle.
    Recovery fills up to MAX_PLAY_BUDGET_SECONDS, but never reduces budgets
    that are already above that (from extra time or set commands)."""
    # If budget is already above the normal cap (because of extra time),
    # don't change it during idle periods.
    if state.remaining_budget_seconds >= MAX_PLAY_BUDGET_SECONDS:
        return

    cap = MAX_PLAY_BUDGET_SECONDS
    recovered = elapsed_seconds * BUDGET_RECOVERY_PER_SECOND_IDLE
    before = state.remaining_budget_seconds
    state.remaining_budget_seconds = min(cap, state.remaining_budget_seconds + recovered)
    gained = state.remaining_budget_seconds - before

    # If we've fully recovered back to the normal cap, reset the overtime
    # escalation cycle so future over-budget sessions start fresh, and log
    # an explicit message when we hit full budget.
    just_filled = before < cap and state.remaining_budget_seconds >= cap
    if just_filled:
        state.overtime_escalation_level = 0
        state.overtime_next_popup_timestamp = 0.0
        full_str = _format_mmss(state.remaining_budget_seconds)
        full_bar = _format_budget_bar(state, is_recovering=True)
        log.info(
            f"[BUDGET] | full | "
            f"{full_str} remaining | {full_bar}"
        )
        # We already logged the transition to full; no need for an extra
        # '+Xs recovered' line at exactly 100%.
        return

    bar = _format_budget_bar(state, is_recovering=True)
    remaining_str = _format_mmss(state.remaining_budget_seconds)
    log.info(
        f"[BUDGET] | +{gained:.1f}s recovered | "
        f"{remaining_str} remaining | {bar}"
    )


def apply_pending_extra_time(state):
    """Check if the user ran 'hotturkey extra X' and pick up the change.
    Positive = add time, negative = deduct. Budget never goes below 0.

    Pending minutes are stored in a small sidecar file so CLI commands work
    whether the monitor is currently running or not.
    """
    pending_minutes = load_extra_minutes_pending()
    if pending_minutes == 0:
        return

    extra_seconds = pending_minutes * 60
    state.remaining_budget_seconds = max(0.0, state.remaining_budget_seconds + extra_seconds)

    if pending_minutes > 0:
        log.info(
            f"[EXTRA] +{pending_minutes:.1f}min added, "
            f"{state.remaining_budget_seconds:.0f}s remaining"
        )
    else:
        log.info(
            f"[EXTRA] {pending_minutes:.1f}min deducted, "
            f"{state.remaining_budget_seconds:.0f}s remaining"
        )

    # Clear the pending value so we don't apply it again on the next poll
    save_extra_minutes_pending(0.0)


# --- Main update function ---

def update_budget(state):
    """Called every poll cycle by run.py. This is where everything comes together:
    1. Calculate how much time passed since last check
    2. Pick up any extra time from the CLI
    3. Detect if a game or tracked site is focused
    4. If active: start/continue session, subtract from budget
    5. If idle: end session, recover budget"""
    perf_start = time.time()

    now = time.time()
    elapsed_seconds = now - state.last_poll_timestamp

    # Snap elapsed time to neat multiples of the poll interval so logs show
    # clean 5.0s consumed / 2.5s recovered instead of 5.1 / 1.9 due to jitter.
    if elapsed_seconds > 0 and DETECTION_POLL_INTERVAL_SECONDS > 0:
        elapsed_seconds = round(
            elapsed_seconds / DETECTION_POLL_INTERVAL_SECONDS
        ) * DETECTION_POLL_INTERVAL_SECONDS
        if elapsed_seconds < 0:
            elapsed_seconds = 0.0

    state.last_poll_timestamp = now

    # Pick up any extra minutes granted via the CLI.
    apply_pending_extra_time(state)

    # --- PERF: measure major steps inside update_budget ---
    t_idle_start = time.time()

    # Hydrate the known Steam game set from persisted state once per run.
    global _steam_known_initialized
    if not _steam_known_initialized:
        for exe in getattr(state, "known_steam_game_exes", []):
            if exe:
                _KNOWN_STEAM_GAME_NAMES.add(exe.lower())
        _steam_known_initialized = True
    t_idle_end = time.time()

    # Check user idle time (keyboard/mouse). If AFK beyond the threshold, we
    # freeze budget changes unless a tracked activity is actively focused.
    global _was_afk
    idle_check_start = time.time()
    idle_seconds = get_idle_seconds()
    is_afk = idle_seconds >= AFK_IDLE_THRESHOLD_SECONDS
    idle_check_end = time.time()

    if is_afk and not _was_afk:
        log.info(
            f"[IDLE] User AFK (>{AFK_IDLE_THRESHOLD_SECONDS}s), "
            "budget frozen except for active tracking."
        )
    elif not is_afk and _was_afk:
        log.info("[IDLE] User activity resumed.")
    _was_afk = is_afk

    # Keep the known Steam game list fresh so we don't miss exes whose
    # foreground window only appears briefly between polls (e.g. Arc Raiders).
    # This scan is expensive, so we throttle it to at most once every
    # _STEAM_REFRESH_INTERVAL_SECONDS.
    global _last_steam_refresh_time
    refresh_start = refresh_end = perf_start
    if (now - _last_steam_refresh_time) >= _STEAM_REFRESH_INTERVAL_SECONDS:
        refresh_start = time.time()
        refresh_known_steam_games(state)
        refresh_end = time.time()
        _last_steam_refresh_time = time.time()

    detect_start = time.time()
    mode, source_name = detect_tracked_activity()
    detect_end = time.time()

    if mode == "consume":
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
        # End the session if we were previously active; overtime cycle is now
        # only reset when budget has fully recovered back to the cap.
        if state.is_tracked_activity_running:
            log.info(
                f"[SESSION] Ended: {state.tracked_activity_name} "
                f"(used {state.seconds_used_this_session:.0f}s)"
            )
        state.is_tracked_activity_running = False
        state.tracked_activity_name = ""

        # When AFK, we freeze budget during idle/bonus time so you don't farm
        # recovery just by leaving the PC untouched. Active tracked sessions
        # (mode == "consume") ignore AFK so passive watching / controller play
        # still counts.
        if not is_afk:
            # Bonus sites give accelerated recovery instead of idle or consumption.
            if mode == "bonus":
                recover_budget(state, elapsed_seconds * BONUS_RECOVERY_MULTIPLIER)
            else:
                recover_budget(state, elapsed_seconds)

    perf_total = (time.time() - perf_start) * 1000.0
    log.debug(
        "[PERF] update_budget: "
        f"hydrate={ (t_idle_end - t_idle_start) * 1000.0:.1f}ms, "
        f"idle_check={ (idle_check_end - idle_check_start) * 1000.0:.1f}ms, "
        f"refresh_steam={ (refresh_end - refresh_start) * 1000.0:.1f}ms, "
        f"detect={ (detect_end - detect_start) * 1000.0:.1f}ms, "
        f"total={ perf_total:.1f}ms"
    )

    return mode != "idle", source_name
