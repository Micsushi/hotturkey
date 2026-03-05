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
    OVERTIME_INTERVAL_DECAY_FACTOR,
    OVERTIME_MIN_INTERVAL_SECONDS,
)
from hotturkey.logger import log
from hotturkey.state import (
    load_extra_minutes_pending,
    save_extra_minutes_pending,
    load_set_minutes,
    save_set_minutes,
)


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


def _overtime_level_from_debt(overtime_seconds: float) -> int:
    """Compute overtime level (1, 2, 3, ...) from current debt. Matches popup.py logic."""
    if overtime_seconds <= 0:
        return 0
    base_interval = max(
        float(OVERTIME_MIN_INTERVAL_SECONDS),
        0.5 * float(MAX_PLAY_BUDGET_SECONDS),
    )
    level = 1
    remaining_for_higher = max(0.0, overtime_seconds - base_interval)
    if remaining_for_higher > 0:
        level = 2
        interval = base_interval * OVERTIME_INTERVAL_DECAY_FACTOR
        while remaining_for_higher >= interval and interval >= 1.0:
            remaining_for_higher -= interval
            level += 1
            interval *= OVERTIME_INTERVAL_DECAY_FACTOR
            if interval < 1.0:
                break
    return level


def _format_budget_bar(state, is_recovering: bool) -> str:
    """Return an ASCII bar representing how much of the budget is used.

    Example: [██████░░░░░░░░] 25% used (recovering)
             [████████████████] 100% used (overtime L2)
    """
    cap = float(MAX_PLAY_BUDGET_SECONDS) if MAX_PLAY_BUDGET_SECONDS > 0 else 1.0
    remaining_clamped = max(0.0, min(state.remaining_budget_seconds, cap))
    used_ratio = 1.0 - (remaining_clamped / cap)
    used_ratio = max(0.0, min(1.0, used_ratio))

    # Only show 100% when budget is actually fully used (remaining <= 0).
    if state.remaining_budget_seconds > 0 and used_ratio >= 1.0:
        used_ratio = 0.99

    used_blocks = int(round(used_ratio * _BUDGET_BAR_WIDTH))
    used_blocks = max(0, min(_BUDGET_BAR_WIDTH, used_blocks))

    # Use plain ASCII characters so logs work on all Windows encodings.
    # '#' = used time, '-' = remaining time.
    bar = "#" * used_blocks + "-" * (_BUDGET_BAR_WIDTH - used_blocks)
    percent = int(round(used_ratio * 100))

    # Suffix describing state: overtime vs recovering vs full/normal.
    suffix_parts = []
    if state.remaining_budget_seconds <= 0:
        overtime = getattr(state, "overtime_seconds", 0.0)
        if overtime > 0:
            level = _overtime_level_from_debt(overtime)
            suffix_parts.append(f"overtime L{level}")
            suffix_parts.append(f"debt {_format_mmss(overtime)}")
    elif is_recovering:
        if percent == 0:
            suffix_parts.append("full")
        else:
            suffix_parts.append("recovering")

    suffix = ""
    if suffix_parts:
        # Use pipe separators for all extra state info (overtime level, debt, etc.).
        suffix = " | " + " | ".join(suffix_parts)

    return f"[{bar}] {percent:3d}% used{suffix}"

def consume_budget(state, elapsed_seconds):
    """Subtract play time from budget.

    When there is remaining budget, we subtract from it until it reaches 0.
    Any additional time beyond that is tracked separately as overtime_seconds,
    so we can later show and "pay back" that debt before refilling normal
    budget.
    """
    # Ensure the field exists even for older state files.
    if not hasattr(state, "overtime_seconds"):
        state.overtime_seconds = 0.0

    before_budget = state.remaining_budget_seconds
    before_overtime = state.overtime_seconds

    if before_budget > 0:
        new_budget = before_budget - elapsed_seconds
        if new_budget >= 0:
            # All consumption fits within remaining budget.
            state.remaining_budget_seconds = new_budget
            overtime_added = 0.0
        else:
            # We used up the remaining budget and the rest is overtime.
            state.remaining_budget_seconds = 0.0
            overtime_added = -new_budget  # positive seconds over budget
    else:
        # Already at/below zero budget: everything counts as overtime.
        overtime_added = elapsed_seconds

    state.overtime_seconds = max(0.0, before_overtime + overtime_added)

    # For the [BUDGET] line, distinguish between normal budget consumption and
    # overtime accumulation so we never log "-0.0s consumed" when time was
    # actually added to overtime.
    spent = max(0.0, before_budget - state.remaining_budget_seconds)
    bar = _format_budget_bar(state, is_recovering=False)
    remaining_str = _format_mmss(state.remaining_budget_seconds)
    if spent > 0 and overtime_added > 0:
        log.info(
            f"[BUDGET] | -{spent:.1f}s consumed, +{overtime_added:.1f}s overtime | "
            f"{remaining_str} remaining | {bar}"
        )
    elif spent > 0:
        log.info(
            f"[BUDGET] | -{spent:.1f}s consumed | "
            f"{remaining_str} remaining | {bar}"
        )
    else:
        # No normal budget spent this tick, but we may still have gone further
        # into overtime.
        log.info(
            f"[BUDGET] | +{overtime_added:.1f}s overtime | "
            f"{remaining_str} remaining | {bar}"
        )


def recover_budget(state, elapsed_seconds):
    """Add time back to budget while idle or on bonus sites.

    Recovery first pays down any accumulated overtime_seconds (time spent past
    0 budget). Only once overtime_seconds reaches 0 does additional recovery
    start refilling remaining_budget_seconds up to MAX_PLAY_BUDGET_SECONDS.
    Budgets already above the normal cap (from extra time or set commands)
    are not reduced.
    """
    # Ensure the field exists even for older state files.
    if not hasattr(state, "overtime_seconds"):
        state.overtime_seconds = 0.0

    # If budget is already above the normal cap (because of extra time),
    # don't change it during idle periods.
    if state.remaining_budget_seconds >= MAX_PLAY_BUDGET_SECONDS and state.overtime_seconds <= 0:
        return

    cap = MAX_PLAY_BUDGET_SECONDS
    recovered = elapsed_seconds * BUDGET_RECOVERY_PER_SECOND_IDLE

    before_budget = state.remaining_budget_seconds
    before_overtime = state.overtime_seconds

    # Step 1: pay down overtime debt.
    debt_paid = 0.0
    if before_overtime > 0 and recovered > 0:
        debt_paid = min(before_overtime, recovered)
        state.overtime_seconds = before_overtime - debt_paid
        recovered -= debt_paid

    # Step 2: any leftover recovery goes into normal budget (up to the cap).
    gained = 0.0
    if recovered > 0 and state.remaining_budget_seconds < cap:
        state.remaining_budget_seconds = min(cap, state.remaining_budget_seconds + recovered)
        gained = state.remaining_budget_seconds - before_budget

    # If we've fully recovered back to the normal cap and cleared overtime,
    # reset the escalation cycle so future over-budget sessions start fresh.
    just_filled = (
        before_budget < cap
        and state.remaining_budget_seconds >= cap
        and state.overtime_seconds <= 0.0
    )
    if just_filled:
        state.overtime_escalation_level = 0
        state.overtime_next_popup_timestamp = 0.0
        full_str = _format_mmss(state.remaining_budget_seconds)
        full_bar = _format_budget_bar(state, is_recovering=True)
        log.info(
            f"[BUDGET] | full | "
            f"{full_str} remaining | {full_bar}"
        )
        return

    # Log what happened this tick.
    bar = _format_budget_bar(state, is_recovering=True)
    remaining_str = _format_mmss(state.remaining_budget_seconds)

    if debt_paid > 0 and gained > 0:
        # Split line: paid overtime and refilled budget in the same tick.
        log.info(
            f"[BUDGET] | +{debt_paid:.1f}s overtime repaid, +{gained:.1f}s recovered | "
            f"{remaining_str} remaining | {bar}"
        )
    elif debt_paid > 0:
        log.info(
            f"[BUDGET] | +{debt_paid:.1f}s overtime repaid | "
            f"{remaining_str} remaining | {bar}"
        )
    elif gained > 0:
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

    # Ensure overtime field exists even for older state files.
    if not hasattr(state, "overtime_seconds"):
        state.overtime_seconds = 0.0

    extra_seconds = pending_minutes * 60
    before_budget = state.remaining_budget_seconds
    before_overtime = state.overtime_seconds

    debt_cleared = 0.0
    budget_delta = 0.0

    if extra_seconds > 0:
        # Positive extra time: first clear overtime debt, then add any leftover
        # to normal budget (which may go above the usual cap, as before).
        debt_cleared = min(before_overtime, extra_seconds)
        state.overtime_seconds = before_overtime - debt_cleared
        extra_seconds -= debt_cleared

        if extra_seconds != 0.0:
            state.remaining_budget_seconds = max(0.0, before_budget + extra_seconds)
            budget_delta = state.remaining_budget_seconds - before_budget

        log.info(
            "[EXTRA] "
            f"+{pending_minutes:.1f}min applied "
            f"(cleared {debt_cleared/60.0:.1f}min overtime, "
            f"+{budget_delta/60.0:.1f}min budget), "
            f"{state.remaining_budget_seconds:.0f}s remaining, "
            f"debt {state.overtime_seconds:.0f}s"
        )
    else:
        # Negative extra time: treat as taking time away. We subtract from
        # remaining budget first; if that would go below 0, the rest becomes
        # additional overtime debt.
        delta = extra_seconds  # negative
        new_budget = before_budget + delta
        if new_budget >= 0:
            state.remaining_budget_seconds = new_budget
            budget_delta = delta
        else:
            state.remaining_budget_seconds = 0.0
            overdraw = -new_budget  # positive seconds that went past 0
            state.overtime_seconds = before_overtime + overdraw
            budget_delta = -before_budget

        log.info(
            "[EXTRA] "
            f"{pending_minutes:.1f}min deducted "
            f"(budget change {budget_delta/60.0:.1f}min), "
            f"{state.remaining_budget_seconds:.0f}s remaining, "
            f"debt {state.overtime_seconds:.0f}s"
        )

    # Clear the pending value so we don't apply it again on the next poll.
    save_extra_minutes_pending(0.0)


def apply_pending_set_time(state):
    """Check if the user ran 'hotturkey set X' and pick up the change.

    Semantics:
      - Positive minutes: budget is set to exactly X minutes remaining,
        overtime is cleared to 0.
      - Negative minutes: budget is set to 0, overtime debt is set to
        abs(X) minutes.
      - Zero minutes: no-op.

    This acts as an override on top of whatever the current state is, and
    runs before extra-time adjustments.
    """
    minutes = load_set_minutes()
    if minutes == 0:
        return

    # Ensure overtime field exists even for older state files.
    if not hasattr(state, "overtime_seconds"):
        state.overtime_seconds = 0.0

    if minutes > 0:
        state.remaining_budget_seconds = float(minutes * 60)
        state.overtime_seconds = 0.0
        # Reset overtime escalation cycle; we're effectively starting fresh.
        state.overtime_escalation_level = 0
        state.overtime_next_popup_timestamp = 0.0
        log.info(
            f"[SET] Budget set to {minutes:.1f}min remaining, overtime cleared."
        )
    elif minutes < 0:
        debt_minutes = abs(minutes)
        state.remaining_budget_seconds = 0.0
        state.overtime_seconds = float(debt_minutes * 60)
        # Level will be recomputed from overtime_seconds by popup logic.
        log.info(
            f"[SET] Overtime set to {debt_minutes:.1f}min (budget 0)."
        )

    # Clear the pending value so we don't apply it again on the next poll.
    save_set_minutes(0.0)


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

    # Pick up any pending 'set' overrides, then extra minutes from the CLI.
    apply_pending_set_time(state)
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
    # freeze budget changes for idle/bonus time and (optionally) some tracked
    # activities depending on their type.
    global _was_afk
    idle_check_start = time.time()
    idle_seconds = get_idle_seconds()
    is_afk = idle_seconds >= AFK_IDLE_THRESHOLD_SECONDS
    idle_check_end = time.time()

    if is_afk and not _was_afk:
        log.info(
            f"[IDLE] User AFK (>{AFK_IDLE_THRESHOLD_SECONDS}s)."
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
        is_steam_session = source_name.startswith("Steam:")
        # Start a new session if this is the first detection
        if not state.is_tracked_activity_running:
            log.info(f"[SESSION] Started: {source_name}")
            state.current_session_start_timestamp = now
            state.seconds_used_this_session = 0.0
            state.has_shown_gentle_reminder = False

        state.is_tracked_activity_running = True
        state.tracked_activity_name = source_name

        # AFK handling:
        # - For Steam games: when AFK, freeze budget (don't consume or advance session time),
        #   so idling in a game menu doesn't drain time.
        # - For tracked sites (YouTube, etc.): always count, even if AFK from
        #   keyboard/mouse, since you're still watching.
        if is_afk and is_steam_session:
            log.debug("[IDLE] AFK during Steam session; freezing budget this tick.")
        else:
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
