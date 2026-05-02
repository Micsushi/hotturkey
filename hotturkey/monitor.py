# monitor.py -- The brain of the app.
# Detects what is focused, then consumes or recovers budget accordingly

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
    MAX_PLAY_BUDGET,
    get_effective_max_extra_minutes_per_day,
    BUDGET_RECOVERY_PER_SECOND_RATIO,
    POLL_INTERVAL,
    BUDGET_ELAPSED_GAP_CLAMP_THRESHOLD_SECONDS,
    BONUS_RECOVERY_MULTIPLIER,
    BONUS_APPS_RECOVERY_MULTIPLIER,
    AFK_IDLE_THRESHOLD,
    SOCIAL_CONSUME_RATIO,
)
from hotturkey.logger import log, log_event
from hotturkey.utils import format_duration
from hotturkey.tracked_targets import get_tracked_targets
from hotturkey.state import (
    load_extra_minutes_pending,
    save_extra_minutes_pending,
    load_extra_minutes_given_today,
    add_extra_minutes_given_today,
    load_set_minutes,
    save_set_minutes,
    apply_extra_seconds,
    overtime_level_from_debt,
    _VALID_MANUAL_ACTIVITY_MODES,
    load_manual_activity_overrides,
)

# Names (lowercase) of executables that are currently detected as Steam descendants.
# This is intentionally NOT a historical "learned forever" list, to avoid misclassifying
# unrelated apps (e.g. browsers) that were once launched via Steam.
_KNOWN_STEAM_GAME_NAMES = set()
_BUDGET_BAR_WIDTH = 16
_was_afk = False
_last_focused_activity = None
_steam_known_initialized = False
_STEAM_REFRESH_INTERVAL_SECONDS = 5.0
_last_steam_refresh_time = 0.0


# --- activity detection ---
class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwTime", wintypes.DWORD),
    ]


_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32


def get_idle_seconds() -> float:
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not _user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    millis_since_input = _kernel32.GetTickCount() - info.dwTime
    return max(0.0, millis_since_input / 1000.0)


def get_foreground_window_info():
    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return 0, ""
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    title = win32gui.GetWindowText(hwnd)
    return pid, title


def foreground_exe_basename_lower(pid: int) -> str:
    if pid <= 0:
        return ""
    try:
        return psutil.Process(pid).name().lower()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.Error):
        return ""


def is_steam_ancestor(pid):
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
    try:
        current_names = set()
        steam_procs = []
        for proc in psutil.process_iter(["pid", "name"]):
            name = proc.info.get("name") or ""
            if not name:
                continue
            if name.lower() == STEAM_PROCESS_NAME:
                steam_procs.append(proc)

        if not steam_procs:
            _KNOWN_STEAM_GAME_NAMES.clear()
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
                if lname in STEAM_HELPER_PROCESS_NAMES:
                    continue

                current_names.add(lname)
                if lname not in (ex.lower() for ex in state.known_steam_game_exes):
                    state.known_steam_game_exes.append(lname)
                log_event("GAMING", message=f"learned: {name}")
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.Error):
        pass
    else:
        # Replace the working set each refresh so stale "learned" names don't stick forever.
        _KNOWN_STEAM_GAME_NAMES.clear()
        _KNOWN_STEAM_GAME_NAMES.update(current_names)


def read_steam_env_for_pid(pid: int) -> tuple[str | None, str | None, str]:
    """Return (SteamAppId, SteamGameId, status).

    status is 'ok', 'missing', 'no_process', or 'access_denied' (Windows often
    blocks Process.environ() without elevation for non-owned processes).
    """
    try:
        env = psutil.Process(pid).environ()
    except psutil.NoSuchProcess:
        return None, None, "no_process"
    except psutil.AccessDenied:
        return None, None, "access_denied"
    except psutil.Error:
        return None, None, "error"
    sid = env.get("SteamAppId")
    gid = env.get("SteamGameId")
    if sid or gid:
        return sid, gid, "ok"
    return None, None, "missing"


def has_steam_env(pid: int) -> bool:
    """Return True if the process carries Steam-injected env vars.

    Steam sets SteamAppId and SteamGameId on every game process it launches.
    Child processes inherit those vars, so this detects games launched through
    an intermediate publisher launcher even when the parent-chain check fails.
    """
    sid, gid, status = read_steam_env_for_pid(pid)
    if status in ("no_process", "access_denied", "error"):
        return False
    return bool(sid or gid)


def detect_steam_game_focused(foreground_pid, known_game_executables):
    game_name = ""
    if foreground_pid <= 0:
        return game_name

    try:
        proc = psutil.Process(foreground_pid)
        proc_name = proc.name().lower()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return game_name

    if proc_name in STEAM_HELPER_PROCESS_NAMES:
        return game_name

    if (
        proc_name in _KNOWN_STEAM_GAME_NAMES
        or proc_name in known_game_executables
        or is_steam_ancestor(foreground_pid)
    ):
        game_name = proc.name()
    elif has_steam_env(foreground_pid):
        game_name = proc.name()
        log_event("GAMING", message=f"detected via Steam env: {game_name}")

    return game_name


def parent_process_chain(pid: int, max_levels: int = 14) -> str:
    """Foreground process left, oldest ancestor right."""
    if pid <= 0:
        return "(no foreground window)"
    names: list[str] = []
    try:
        proc = psutil.Process(pid)
        for _ in range(max_levels):
            names.append(proc.name())
            parent = proc.parent()
            if parent is None:
                break
            proc = parent
    except psutil.AccessDenied:
        return " <- ".join(names) + " <- (access denied reading further)"
    except psutil.NoSuchProcess:
        return " <- ".join(names) if names else "(process vanished)"
    return " <- ".join(names)


def foreground_diagnostics_report(state) -> str:
    """One-shot snapshot for debugging classify-miss issues. Refreshes Steam child set."""
    refresh_known_steam_games(state)
    pid, title = get_foreground_window_info()
    lines = [
        "HotTurkey foreground snapshot (focus target window)",
        "",
        f"Window title: {title!r}",
    ]
    if pid <= 0:
        lines.extend(["PID: (none)", "", "Nothing focused or cannot read HWND."])
        return "\n".join(lines)

    lines.append(f"PID: {pid}")
    pname = ""

    try:
        proc = psutil.Process(pid)
        pname = proc.name()
        lines.append(f"Process name (.exe): {pname}")
        try:
            exe_path = proc.exe()
            lines.append(f"Executable path: {exe_path}")
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            lines.append("Executable path: (unavailable)")
    except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
        lines.append(f"(could not inspect process: {exc})")

    steam_app_id, steam_game_id, steam_env_status = read_steam_env_for_pid(pid)
    tt = get_tracked_targets()
    exe_set = tt["known_game_executables"]

    lines.extend(
        [
            "",
            f"Parent chain: {parent_process_chain(pid)}",
            "",
            f"Steam ancestry (walk parents for steam.exe): {'yes' if is_steam_ancestor(pid) else 'no'}",
            f"In current Steam descendant set ({len(_KNOWN_STEAM_GAME_NAMES)} exe names): "
            f"{'yes' if pname.lower() in _KNOWN_STEAM_GAME_NAMES else 'no'}",
            f"In tracked_targets.json known_game_executables: "
            f"{'yes' if pname.lower() in exe_set else 'no'}",
            f"Steam env read: status={steam_env_status}"
            + (
                f", SteamAppId={steam_app_id!r}, SteamGameId={steam_game_id!r}"
                if steam_env_status == "ok" and (steam_app_id or steam_game_id)
                else ""
            ),
        ]
    )
    if steam_env_status == "access_denied":
        lines.append(
            "  (HotTurkey cannot read this process environ without elevation; Steam "
            "env detection will not fire. Add exe under known_game_executables in "
            "tracked_targets.json if needed.)"
        )

    exe_lc = pname.lower() if pname else ""
    overrides = load_manual_activity_overrides()
    if exe_lc and exe_lc in overrides:
        lines.extend(["", f"manual_activity_override: {overrides[exe_lc]!r}"])

    if pname:
        steam_label = detect_steam_game_focused(pid, exe_set)
        lines.extend(
            [
                "",
                f"detect_steam_game_focused: {steam_label or '(empty)'}",
            ]
        )

    mode, label = detect_tracked_activity()
    lines.extend(
        [
            "",
            "HotTurkey would use (first match: manual exe override > bonus sites > "
            "bonus apps > steam > browser keywords > social):",
            f"  mode={mode!r}",
            f"  label={label!r}",
        ]
    )
    return "\n".join(lines)


# Should look into something better than this
def detect_tracked_site_focused(foreground_title, tracked_sites, tracked_browsers):
    title_lower = foreground_title.lower()
    for site in tracked_sites:
        if site in title_lower:
            browser = next(
                (b for b in tracked_browsers if b in title_lower),
                None,
            )
            if browser:
                return f"{site.title()} ({browser.title()})"
            return f"{site.title()}"
    return ""


def _match_title_keyword(foreground_title, keywords):
    title_lower = foreground_title.lower()
    for name in keywords:
        if name in title_lower:
            return name.replace("-", " ").title()
    return ""


def detect_bonus_site_focused(foreground_title, bonus_sites):
    return _match_title_keyword(foreground_title, bonus_sites)


def detect_bonus_app_focused(foreground_title, bonus_apps):
    if not bonus_apps:
        return ""
    return _match_title_keyword(foreground_title, bonus_apps)


def detect_social_focused(foreground_title, social_keywords):
    return _match_title_keyword(foreground_title, social_keywords)


def detect_tracked_activity():
    foreground_pid, foreground_title = get_foreground_window_info()
    tt = get_tracked_targets()

    mode = ""
    label = ""

    exe_key = foreground_exe_basename_lower(foreground_pid)
    if exe_key:
        ovr = load_manual_activity_overrides()
        row = ovr.get(exe_key)
        if isinstance(row, dict):
            override_mode = row.get("mode")
            override_label = row.get("label")
            if override_mode in _VALID_MANUAL_ACTIVITY_MODES and isinstance(
                override_label, str
            ):
                mode = override_mode
                label = override_label

    if not label:
        mode = "bonus"
        label = detect_bonus_site_focused(foreground_title, tt["bonus_sites"])

    if not label:
        mode = "bonus_app"
        label = detect_bonus_app_focused(foreground_title, tt["bonus_apps"])

    if not label:
        steam_game_name = detect_steam_game_focused(
            foreground_pid, tt["known_game_executables"]
        )
        if steam_game_name:
            mode = "consume"
            label = f"Steam: {steam_game_name}"

    if not label:
        mode = "consume"
        label = detect_tracked_site_focused(
            foreground_title,
            tt["tracked_sites"],
            tt["browsers"],
        )

    if not label:
        mode = "social"
        label = detect_social_focused(
            foreground_title,
            tt["social_apps_or_sites"],
        )

    if label:
        return mode, label

    log.debug("[IDLE] status=no_activity")
    return "idle", ""


# --- budget ---
def _format_budget_bar(state, is_recovering: bool) -> str:
    cap = float(MAX_PLAY_BUDGET) if MAX_PLAY_BUDGET > 0 else 1.0
    remaining_clamped = max(0.0, min(state.remaining_budget_seconds, cap))
    used_ratio = 1.0 - (remaining_clamped / cap)
    used_ratio = max(0.0, min(1.0, used_ratio))

    # Only show 100% when budget is actually finished
    if state.remaining_budget_seconds > 0 and used_ratio >= 1.0:
        used_ratio = 0.99

    used_blocks = int(round(used_ratio * _BUDGET_BAR_WIDTH))
    used_blocks = max(0, min(_BUDGET_BAR_WIDTH, used_blocks))

    bar = "#" * used_blocks + "-" * (_BUDGET_BAR_WIDTH - used_blocks)
    percent = int(round(used_ratio * 100))

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
        suffix = " | " + " | ".join(suffix_parts)

    return f"[{bar}] {percent:3d}% used{suffix}"


def _maybe_reset_session_totals_for_today(state) -> None:
    today_str = date.today().isoformat()
    if getattr(state, "session_totals_date", "") != today_str:
        from hotturkey.db import upsert_daily_totals

        upsert_daily_totals(state)
        state.gaming_seconds_today = 0.0
        state.entertainment_seconds_today = 0.0
        state.social_seconds_today = 0.0
        state.bonus_sites_seconds_today = 0.0
        state.bonus_apps_seconds_today = 0.0
        state.other_apps_seconds_today = 0.0
        state.session_totals_date = today_str


def _add_session_time_to_daily_totals(state, seconds_used: float) -> None:
    if seconds_used <= 0:
        return
    mode = getattr(state, "current_session_mode", "")
    if mode == "consume":
        label = getattr(state, "tracked_activity_name", "") or ""
        if label.startswith("Steam:"):
            state.gaming_seconds_today = getattr(
                state, "gaming_seconds_today", 0.0
            ) + float(seconds_used)
        else:
            state.entertainment_seconds_today = getattr(
                state, "entertainment_seconds_today", 0.0
            ) + float(seconds_used)
    elif mode == "bonus":
        state.bonus_sites_seconds_today = getattr(
            state, "bonus_sites_seconds_today", 0.0
        ) + float(seconds_used)
    elif mode == "bonus_app":
        state.bonus_apps_seconds_today = getattr(
            state, "bonus_apps_seconds_today", 0.0
        ) + float(seconds_used)
    elif mode == "social":
        state.social_seconds_today = getattr(
            state, "social_seconds_today", 0.0
        ) + float(seconds_used)


def _end_session(state) -> None:
    if not state.is_tracked_activity_running:
        return
    used_s = int(state.seconds_used_this_session)
    _add_session_time_to_daily_totals(state, used_s)

    if used_s > 0:
        from hotturkey.db import insert_session

        now = time.time()
        insert_session(
            date_str=getattr(state, "session_totals_date", date.today().isoformat()),
            activity=state.tracked_activity_name,
            mode=getattr(state, "current_session_mode", ""),
            start_ts=state.current_session_start_timestamp,
            end_ts=now,
            duration_s=used_s,
        )

    log_event(
        "SESSION",
        message=f"session ended: {state.tracked_activity_name}, {used_s}s used",
    )
    state.is_tracked_activity_running = False
    state.tracked_activity_name = ""


def _start_session(state, source_name: str, mode: str, now: float) -> None:
    if state.is_tracked_activity_running:
        return
    log_event("SESSION", message=f"session started: {source_name}")
    state.current_session_start_timestamp = now
    state.seconds_used_this_session = 0.0
    state.current_session_mode = mode


# If the PC was asleep (or we missed many polls), don't count the gap as one huge step
def clamp_elapsed_for_budget(elapsed_seconds: float) -> float:
    if elapsed_seconds <= 0 or POLL_INTERVAL <= 0:
        return elapsed_seconds
    threshold = max(
        float(BUDGET_ELAPSED_GAP_CLAMP_THRESHOLD_SECONDS),
        3.0 * float(POLL_INTERVAL),
    )
    if elapsed_seconds > threshold:
        return float(POLL_INTERVAL)
    return elapsed_seconds


def consume_budget(state, elapsed_seconds):
    if elapsed_seconds <= 0:
        return

    before_budget = state.remaining_budget_seconds
    before_overtime = state.overtime_seconds

    # consume budget before adding overtime debt
    if before_budget > 0:
        new_budget = before_budget - elapsed_seconds
        if new_budget >= 0:
            state.remaining_budget_seconds = new_budget
            overtime_added = 0.0
        else:
            state.remaining_budget_seconds = 0.0
            overtime_added = -new_budget
    else:
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
    if (
        state.remaining_budget_seconds >= MAX_PLAY_BUDGET
        and state.overtime_seconds <= 0
    ):
        return

    cap = MAX_PLAY_BUDGET
    recovered = elapsed_seconds * BUDGET_RECOVERY_PER_SECOND_RATIO

    before_budget = state.remaining_budget_seconds
    before_overtime = state.overtime_seconds

    # pay overtime first.
    debt_paid = 0.0
    if before_overtime > 0 and recovered > 0:
        debt_paid = min(before_overtime, recovered)
        state.overtime_seconds = before_overtime - debt_paid
        recovered -= debt_paid

    # recover normal budget
    gained = 0.0
    if recovered > 0 and state.remaining_budget_seconds < cap:
        state.remaining_budget_seconds = min(
            cap, state.remaining_budget_seconds + recovered
        )
        gained = state.remaining_budget_seconds - before_budget

    bar = _format_budget_bar(state, is_recovering=True)
    remaining_str = format_duration(state.remaining_budget_seconds)
    budget_delta = gained
    overtime_delta = -debt_paid
    if budget_delta != 0 or overtime_delta != 0:
        log.info(
            f"[BUDGET] | budget {budget_delta:+.1f}s | overtime {overtime_delta:+.1f}s | "
            f"{remaining_str} remaining | {bar}"
        )


# --- CLI pending ---
def apply_pending_set_time(state):
    minutes = load_set_minutes()
    if minutes == 0:
        return

    if minutes > 0:
        state.remaining_budget_seconds = float(minutes * 60)
        state.overtime_seconds = 0.0
        state.overtime_escalation_level = 0
        log.info(
            "[COMMAND] set: budget to %.1f min, overtime cleared.",
            minutes,
        )
    elif minutes < 0:
        debt_minutes = abs(minutes)
        state.remaining_budget_seconds = 0.0
        state.overtime_seconds = float(debt_minutes * 60)
        log.info(
            "[COMMAND] set: overtime to %.1f min (budget 0).",
            debt_minutes,
        )

    save_set_minutes(0.0)


def apply_pending_extra_time(state):
    pending_minutes = load_extra_minutes_pending()
    if pending_minutes == 0:
        return

    extra_seconds = pending_minutes * 60
    before_budget = state.remaining_budget_seconds
    before_overtime = state.overtime_seconds

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
    extra_cap = get_effective_max_extra_minutes_per_day()

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
                extra_cap,
            )
        elif debt_cleared > 0:
            log.info(
                "[COMMAND] extra: +%.1f min (reduced overtime). Budget: %s, overtime: %s, extra today: %d/%d",
                pending_minutes,
                remaining_str,
                debt_str,
                extra_today,
                extra_cap,
            )
        else:
            log.info(
                "[COMMAND] extra: +%.1f min to budget. Budget: %s, overtime: %s, extra today: %d/%d",
                pending_minutes,
                remaining_str,
                debt_str,
                extra_today,
                extra_cap,
            )
    else:
        log.info(
            "[COMMAND] extra: -%.1f min. Budget: %s, overtime: %s, extra today: %d/%d",
            abs(pending_minutes),
            remaining_str,
            debt_str,
            extra_today,
            extra_cap,
        )

    # Clear the pending value so we don't apply it again on the next poll.
    save_extra_minutes_pending(0.0)


# --- main poll ---
def _update_tracked_session(state, source_name, session_mode, now, elapsed_seconds):
    if state.tracked_activity_name != source_name:
        _end_session(state)
    _start_session(state, source_name, session_mode, now)
    state.is_tracked_activity_running = True
    state.tracked_activity_name = source_name
    state.seconds_used_this_session += elapsed_seconds


def _init_steam_games(_state):
    global _steam_known_initialized
    if _steam_known_initialized:
        return
    # Do not seed the current Steam-descendant set from historical state.
    # The refresh loop will repopulate from actual Steam processes.
    _steam_known_initialized = True


def _update_afk_state():
    global _was_afk
    idle_seconds = get_idle_seconds()
    is_afk = idle_seconds >= AFK_IDLE_THRESHOLD
    if is_afk and not _was_afk:
        log_event("IDLE", message=f"afk (idle {AFK_IDLE_THRESHOLD}s)")
    elif not is_afk and _was_afk:
        log_event("IDLE", message="resumed")
    _was_afk = is_afk
    return is_afk


def _maybe_refresh_steam(state, now):
    global _last_steam_refresh_time
    if (now - _last_steam_refresh_time) >= _STEAM_REFRESH_INTERVAL_SECONDS:
        refresh_known_steam_games(state)
        _last_steam_refresh_time = time.time()


def _log_focus_change(mode, source_name):
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


def _apply_mode_budget(state, mode, source_name, is_afk, now, elapsed_seconds):
    if mode == "consume":
        is_steam_session = source_name.startswith("Steam:")
        if is_afk and is_steam_session:
            _update_tracked_session(state, source_name, "consume", now, 0)
            log.debug("[IDLE] event=afk_steam_freezing_budget")
        else:
            _update_tracked_session(state, source_name, "consume", now, elapsed_seconds)
            consume_budget(state, elapsed_seconds)
    elif mode == "bonus":
        _update_tracked_session(state, source_name, "bonus", now, elapsed_seconds)
        if not is_afk:
            recover_budget(state, elapsed_seconds * BONUS_RECOVERY_MULTIPLIER)
    elif mode == "bonus_app":
        _update_tracked_session(state, source_name, "bonus_app", now, elapsed_seconds)
        if not is_afk:
            recover_budget(state, elapsed_seconds * BONUS_APPS_RECOVERY_MULTIPLIER)
    elif mode == "social":
        _update_tracked_session(state, source_name, "social", now, elapsed_seconds)
        consume_budget(state, elapsed_seconds * SOCIAL_CONSUME_RATIO)
    else:
        _end_session(state)
        if not is_afk:
            state.other_apps_seconds_today = getattr(
                state, "other_apps_seconds_today", 0.0
            ) + float(elapsed_seconds)
            recover_budget(state, elapsed_seconds)


def update_budget(state):
    now = time.time()
    elapsed_seconds = now - state.last_poll_timestamp

    if elapsed_seconds > 0 and POLL_INTERVAL > 0:
        elapsed_seconds = round(elapsed_seconds / POLL_INTERVAL) * POLL_INTERVAL

    elapsed_seconds = clamp_elapsed_for_budget(elapsed_seconds)
    state.last_poll_timestamp = now

    _maybe_reset_session_totals_for_today(state)
    apply_pending_set_time(state)
    apply_pending_extra_time(state)

    _init_steam_games(state)
    is_afk = _update_afk_state()
    _maybe_refresh_steam(state, now)

    mode, source_name = detect_tracked_activity()
    _log_focus_change(mode, source_name)
    _apply_mode_budget(state, mode, source_name, is_afk, now, elapsed_seconds)

    return mode != "idle", source_name
