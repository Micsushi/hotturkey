# monitor.py -- The brain of the app.
# Detects if a Steam game or tracked site is focused, then consumes or recovers budget.
# Called every 5 seconds by the monitor loop in run.py.

import psutil
import win32gui
import win32process

import ctypes
import ctypes.wintypes as wintypes
import time
from datetime import date

from hotturkey.config import (
    STEAM_PROCESS_NAME,
    STEAM_HELPER_PROCESS_NAMES,
    TRACKED_BROWSERS,
    TRACKED_SITES,
    MAX_PLAY_BUDGET,
    MAX_EXTRA_MINUTES_PER_DAY,
    BUDGET_RECOVERY_PER_SECOND_RATIO,
    POLL_INTERVAL,
    BONUS_SITES,
    BONUS_RECOVERY_MULTIPLIER,
    BONUS_APPS,
    BONUS_APPS_RECOVERY_MULTIPLIER,
    AFK_IDLE_THRESHOLD,
    SOCIAL_APPS_OR_SITES,
    SOCIAL_CONSUME_RATIO,
)
from hotturkey.logger import log, log_event
from hotturkey.utils import format_duration
from hotturkey.state import (
    load_extra_minutes_pending,
    save_extra_minutes_pending,
    load_extra_minutes_given_today,
    add_extra_minutes_given_today,
    load_set_minutes,
    save_set_minutes,
    apply_extra_seconds,
    overtime_level_from_debt,
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

# Only log WATCHING/BONUS/GAMING when the focused activity changes, not every poll.
_last_focused_activity = None

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
                if (
                    lname in STEAM_HELPER_PROCESS_NAMES
                    or lname in _KNOWN_STEAM_GAME_NAMES
                ):
                    continue

                _KNOWN_STEAM_GAME_NAMES.add(lname)
                if lname not in (ex.lower() for ex in state.known_steam_game_exes):
                    state.known_steam_game_exes.append(lname)
                log_event("GAMING", message=f"learned: {name}")
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


def _match_title_keyword(foreground_title, keywords):
    """Return a nicely formatted label if any keyword appears in the window title."""
    title_lower = foreground_title.lower()
    for name in keywords:
        if name in title_lower:
            # Capitalize nicely for display (e.g. 'leetcode' -> 'Leetcode').
            return name.replace("-", " ").title()
    return ""


def detect_bonus_site_focused(foreground_title):
    """Check if the focused window is a 'bonus' (productive) site."""
    return _match_title_keyword(foreground_title, BONUS_SITES)


def detect_bonus_app_focused(foreground_title):
    """Check if the focused window looks like a 'good' desktop app that should earn bonus time.
    Matches by title keyword against BONUS_APPS."""
    if not BONUS_APPS:
        return ""
    return _match_title_keyword(foreground_title, BONUS_APPS)


def detect_social_focused(foreground_title):
    """Check if the focused window looks like a social app/site (e.g. Discord, WhatsApp)."""
    return _match_title_keyword(foreground_title, SOCIAL_APPS_OR_SITES)


def detect_tracked_activity():
    """The main detection function. Checks the focused window against all detectors.
    Returns (mode, source_name) where mode is one of:
      - 'consume'   : tracked entertainment (Steam / tracked video sites)
      - 'social'    : social media apps/sites (Discord, WhatsApp) at reduced rate
      - 'bonus'     : productive / bonus sites in the browser (fastest recovery)
      - 'bonus_app' : productive desktop apps (slower 2x recovery)
      - 'idle'      : nothing relevant focused
    """
    foreground_pid, foreground_title = get_foreground_window_info()

    # Bonus / productive sites first: we don't want to consume budget here.
    bonus_label = detect_bonus_site_focused(foreground_title)
    if bonus_label:
        return "bonus", bonus_label

    bonus_app_label = detect_bonus_app_focused(foreground_title)
    if bonus_app_label:
        return "bonus_app", bonus_app_label

    steam_game_name = detect_steam_game_focused(foreground_pid)
    if steam_game_name:
        return "consume", f"Steam: {steam_game_name}"

    browser_match = detect_tracked_site_focused(foreground_title)
    if browser_match:
        return "consume", browser_match

    social_label = detect_social_focused(foreground_title)
    if social_label:
        return "social", social_label

    log.debug("[IDLE] status=no_activity")
    return "idle", ""


# --- Budget logic ---


def _format_budget_bar(state, is_recovering: bool) -> str:
    """Return an ASCII bar representing how much of the budget is used.

    Example: [██████░░░░░░░░] 25% used (repaying budget)
             [████████████████] 100% used (overtime L2)
    """
    cap = float(MAX_PLAY_BUDGET) if MAX_PLAY_BUDGET > 0 else 1.0
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
            level = overtime_level_from_debt(overtime)
            suffix_parts.append(f"overtime L{level} {format_duration(overtime)}")
    elif is_recovering:
        if state.remaining_budget_seconds >= cap and state.overtime_seconds <= 0:
            suffix_parts.append("full")
        else:
            suffix_parts.append("repaying budget")
    else:
        suffix_parts.append("consuming budget")

    suffix = ""
    if suffix_parts:
        # Use pipe separators for all extra state info (overtime level, overtime, etc.).
        suffix = " | " + " | ".join(suffix_parts)

    return f"[{bar}] {percent:3d}% used{suffix}"


def _maybe_reset_session_totals_for_today(state) -> None:
    """Ensure per-day session totals are for today's date; reset if the day changed."""
    today_str = date.today().isoformat()
    if getattr(state, "session_totals_date", "") != today_str:
        state.gaming_seconds_today = 0.0
        state.watching_seconds_today = 0.0
        state.bonus_seconds_today = 0.0
        state.social_seconds_today = 0.0
        state.other_apps_seconds_today = 0.0
        state.session_totals_date = today_str


def _add_session_time_to_totals(state, seconds_used: float) -> None:
    """Accumulate finished session time into today's totals by mode."""
    if seconds_used <= 0:
        return
    mode = getattr(state, "current_session_mode", "")
    if mode == "consume":
        label = getattr(state, "tracked_activity_name", "") or ""
        if label.startswith("Steam:"):
            # Gaming session (Steam)
            state.gaming_seconds_today = getattr(
                state, "gaming_seconds_today", 0.0
            ) + float(seconds_used)
        else:
            # Tracked browser / WATCHING session
            state.watching_seconds_today = getattr(
                state, "watching_seconds_today", 0.0
            ) + float(seconds_used)
    elif mode == "bonus":
        state.bonus_seconds_today = getattr(state, "bonus_seconds_today", 0.0) + float(
            seconds_used
        )
    elif mode == "social":
        state.social_seconds_today = getattr(
            state, "social_seconds_today", 0.0
        ) + float(seconds_used)


def _end_session(state) -> None:
    """End the current tracked session: accumulate time into today's totals, log, and clear."""
    if not state.is_tracked_activity_running:
        return
    used_s = int(state.seconds_used_this_session)
    _add_session_time_to_totals(state, used_s)
    log_event(
        "SESSION",
        message=f"session ended: {state.tracked_activity_name}, {used_s}s used",
    )
    state.is_tracked_activity_running = False
    state.tracked_activity_name = ""


def _start_session(state, source_name: str, mode: str, now: float) -> None:
    """Start a new tracked session if one isn't already running."""
    if state.is_tracked_activity_running:
        return
    log_event("SESSION", message=f"session started: {source_name}")
    state.current_session_start_timestamp = now
    state.seconds_used_this_session = 0.0
    state.current_session_mode = mode


def consume_budget(state, elapsed_seconds):
    """Subtract play time from budget.

    When there is remaining budget, we subtract from it until it reaches 0.
    Any additional time beyond that is tracked separately as overtime_seconds,
    so we can later show and "pay back" that debt before refilling normal
    budget.
    """
    if elapsed_seconds <= 0:
        return

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

    spent = max(0.0, before_budget - state.remaining_budget_seconds)
    bar = _format_budget_bar(state, is_recovering=False)
    remaining_str = format_duration(state.remaining_budget_seconds)
    budget_delta = -spent
    overtime_delta = overtime_added
    log.info(
        f"[BUDGET] | budget {budget_delta:+.1f}s | overtime {overtime_delta:+.1f}s | "
        f"{remaining_str} remaining | {bar}"
    )


def recover_budget(state, elapsed_seconds):
    """Add time back to budget while idle or on bonus sites.

    Recovery first pays down any accumulated overtime_seconds (time spent past
    0 budget). Only once overtime_seconds reaches 0 does additional recovery
    start refilling remaining_budget_seconds up to MAX_PLAY_BUDGET.
    Budgets already above the normal cap (from extra time or set commands)
    are not reduced.
    """
    # If budget is already above the normal cap (because of extra time),
    # don't change it during idle periods.
    if (
        state.remaining_budget_seconds >= MAX_PLAY_BUDGET
        and state.overtime_seconds <= 0
    ):
        return

    cap = MAX_PLAY_BUDGET
    recovered = elapsed_seconds * BUDGET_RECOVERY_PER_SECOND_RATIO

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
        state.remaining_budget_seconds = min(
            cap, state.remaining_budget_seconds + recovered
        )
        gained = state.remaining_budget_seconds - before_budget

    # If we've fully recovered back to the normal cap and cleared overtime,
    # reset the escalation cycle so future over-budget sessions start fresh.
    just_filled = (
        bool(before_budget < cap)
        and bool(state.remaining_budget_seconds >= cap)
        and bool(state.overtime_seconds <= 0.0)
    )
    if just_filled:
        state.overtime_escalation_level = 0
        state.overtime_next_popup_timestamp = 0.0

    bar = _format_budget_bar(state, is_recovering=True)
    remaining_str = format_duration(state.remaining_budget_seconds)
    budget_delta = gained
    overtime_delta = -debt_paid
    if budget_delta != 0 or overtime_delta != 0:
        log.info(
            f"[BUDGET] | budget {budget_delta:+.1f}s | overtime {overtime_delta:+.1f}s | "
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
    before_budget = state.remaining_budget_seconds
    before_overtime = state.overtime_seconds

    # Core math shared with CLI.
    budget_after, overtime_after = apply_extra_seconds(
        before_budget, before_overtime, extra_seconds
    )

    budget_delta = budget_after - before_budget

    state.remaining_budget_seconds = budget_after
    state.overtime_seconds = overtime_after

    # Record positive extra minutes against the daily cap before logging.
    if pending_minutes > 0:
        add_extra_minutes_given_today(pending_minutes)

    remaining_str = format_duration(state.remaining_budget_seconds)
    debt_str = format_duration(state.overtime_seconds)
    extra_today = int(load_extra_minutes_given_today())

    if extra_seconds > 0:
        debt_cleared = max(0.0, before_overtime - overtime_after)
        if debt_cleared > 0 and budget_delta > 0:
            log.info(
                "[COMMAND] extra: +%.1f min (reduced overtime, +%.1f min to budget). Budget: %s, overtime: %s, extra today: %d/%d",
                pending_minutes,
                budget_delta / 60.0,
                remaining_str,
                debt_str,
                extra_today,
                MAX_EXTRA_MINUTES_PER_DAY,
            )
        elif debt_cleared > 0:
            log.info(
                "[COMMAND] extra: +%.1f min (reduced overtime). Budget: %s, overtime: %s, extra today: %d/%d",
                pending_minutes,
                remaining_str,
                debt_str,
                extra_today,
                MAX_EXTRA_MINUTES_PER_DAY,
            )
        else:
            log.info(
                "[COMMAND] extra: +%.1f min to budget. Budget: %s, overtime: %s, extra today: %d/%d",
                pending_minutes,
                remaining_str,
                debt_str,
                extra_today,
                MAX_EXTRA_MINUTES_PER_DAY,
            )
    else:
        log.info(
            "[COMMAND] extra: -%.1f min. Budget: %s, overtime: %s, extra today: %d/%d",
            abs(pending_minutes),
            remaining_str,
            debt_str,
            extra_today,
            MAX_EXTRA_MINUTES_PER_DAY,
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

    if minutes > 0:
        state.remaining_budget_seconds = float(minutes * 60)
        state.overtime_seconds = 0.0
        # Reset overtime escalation cycle; we're effectively starting fresh.
        state.overtime_escalation_level = 0
        state.overtime_next_popup_timestamp = 0.0
        log.info(
            "[COMMAND] set: budget to %.1f min, overtime cleared.",
            minutes,
        )
    elif minutes < 0:
        debt_minutes = abs(minutes)
        state.remaining_budget_seconds = 0.0
        state.overtime_seconds = float(debt_minutes * 60)
        # Level will be recomputed from overtime_seconds by popup logic.
        log.info(
            "[COMMAND] set: overtime to %.1f min (budget 0).",
            debt_minutes,
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
    if elapsed_seconds > 0 and POLL_INTERVAL > 0:
        elapsed_seconds = round(elapsed_seconds / POLL_INTERVAL) * POLL_INTERVAL
        if elapsed_seconds < 0:
            elapsed_seconds = 0.0

    state.last_poll_timestamp = now

    # Keep per-day session totals in sync with the current date.
    _maybe_reset_session_totals_for_today(state)

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
    is_afk = idle_seconds >= AFK_IDLE_THRESHOLD
    idle_check_end = time.time()

    if is_afk and not _was_afk:
        log_event("IDLE", message=f"afk (idle {AFK_IDLE_THRESHOLD}s)")
    elif not is_afk and _was_afk:
        log_event("IDLE", message="resumed")
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

    # Log focus changes: entering an activity (BONUS/WATCHING/GAMING/SOCIAL) or leaving to idle.
    global _last_focused_activity
    if mode == "idle":
        if _last_focused_activity is not None:
            log_event("FOCUS", message="other apps")
        _last_focused_activity = None
    elif source_name != _last_focused_activity:
        _last_focused_activity = source_name
        if mode == "bonus":
            log_event("BONUS", message=f"{source_name} focused")
        elif mode == "bonus_app":
            log_event("BONUS", message=f"app: {source_name} focused")
        elif mode == "consume":
            if source_name.startswith("Steam:"):
                log_event(
                    "GAMING", message=f"{source_name.replace('Steam: ', '')} focused"
                )
            else:
                log_event("WATCHING", message=f"{source_name} focused")
        elif mode == "social":
            log_event("FOCUS", message=f"social: {source_name} focused")

    if mode == "consume":
        is_steam_session = source_name.startswith("Steam:")
        if state.tracked_activity_name != source_name:
            _end_session(state)
        _start_session(state, source_name, "consume", now)

        state.is_tracked_activity_running = True
        state.tracked_activity_name = source_name

        # AFK handling:
        # Steam games: freeze budget when AFK so idling in menus doesn't drain time.
        # Tracked sites: always count (you're still watching even if AFK from keyboard).
        if is_afk and is_steam_session:
            log.debug("[IDLE] event=afk_steam_freezing_budget")
        else:
            state.seconds_used_this_session += elapsed_seconds
            consume_budget(state, elapsed_seconds)
    elif mode == "bonus":
        if state.tracked_activity_name != source_name:
            _end_session(state)
        _start_session(state, source_name, "bonus", now)

        state.is_tracked_activity_running = True
        state.tracked_activity_name = source_name
        state.seconds_used_this_session += elapsed_seconds
        if not is_afk:
            recover_budget(state, elapsed_seconds * BONUS_RECOVERY_MULTIPLIER)
    elif mode == "bonus_app":
        if state.tracked_activity_name != source_name:
            _end_session(state)
        _start_session(state, source_name, "bonus", now)

        state.is_tracked_activity_running = True
        state.tracked_activity_name = source_name
        state.seconds_used_this_session += elapsed_seconds
        if not is_afk:
            recover_budget(state, elapsed_seconds * BONUS_APPS_RECOVERY_MULTIPLIER)
    elif mode == "social":
        if state.tracked_activity_name != source_name:
            _end_session(state)
        _start_session(state, source_name, "social", now)

        state.is_tracked_activity_running = True
        state.tracked_activity_name = source_name
        state.seconds_used_this_session += elapsed_seconds
        # Social media always counts (like watching): no AFK freeze, but budget
        # consumption is reduced by SOCIAL_CONSUME_RATIO.
        consume_budget(state, elapsed_seconds * SOCIAL_CONSUME_RATIO)
    else:
        _end_session(state)

        # When AFK, freeze budget so you don't farm recovery by leaving PC untouched.
        if not is_afk:
            state.other_apps_seconds_today = getattr(
                state, "other_apps_seconds_today", 0.0
            ) + float(elapsed_seconds)
            recover_budget(state, elapsed_seconds)

    perf_total = (time.time() - perf_start) * 1000.0
    log.debug(
        "[PERF] hydrate_ms=%.1f idle_check_ms=%.1f refresh_steam_ms=%.1f detect_ms=%.1f total_ms=%.1f",
        (t_idle_end - t_idle_start) * 1000.0,
        (idle_check_end - idle_check_start) * 1000.0,
        (refresh_end - refresh_start) * 1000.0,
        (detect_end - detect_start) * 1000.0,
        perf_total,
    )

    return mode != "idle", source_name
