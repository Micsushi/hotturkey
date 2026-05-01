# state.py -- Holds all the data the app needs to remember, and saves/loads it as JSON.
# The AppState object gets passed around between the monitor, popup, and tray modules.

import json
import os
import time
from datetime import date

from hotturkey.config import (
    STATE_DIR,
    STATE_FILE,
    MANUAL_ACTIVITY_OVERRIDES_FILE,
    MAX_PLAY_BUDGET,
    OVERTIME_INTERVAL_DECAY_FACTOR,
    OVERTIME_MIN_INTERVAL_SECONDS,
)

_VALID_MANUAL_ACTIVITY_MODES = frozenset({"consume", "bonus", "bonus_app", "social"})


class AppState:
    """Holds everything the app needs to track between poll cycles and across restarts."""

    def __init__(self):
        self.remaining_budget_seconds = float(MAX_PLAY_BUDGET)
        self.overtime_seconds = 0.0
        self.last_poll_timestamp = time.time()
        # Whether a game or tracked site is currently focused
        self.is_tracked_activity_running = False
        # What is being tracked right now, e.g. "Steam: game.exe" or "YouTube (Brave)"
        self.tracked_activity_name = ""
        self.current_session_start_timestamp = 0.0
        self.seconds_used_this_session = 0.0
        self.current_session_mode = ""
        self.overtime_escalation_level = 0
        self.extra_minutes_pending_from_cli = 0.0
        self.gaming_seconds_today = 0.0
        self.entertainment_seconds_today = 0.0
        self.social_seconds_today = 0.0
        self.bonus_sites_seconds_today = 0.0
        self.bonus_apps_seconds_today = 0.0
        self.other_apps_seconds_today = 0.0
        self.session_totals_date = date.today().isoformat()
        self.known_steam_game_exes = []

    def to_dict(self):
        return {
            "remaining_budget_seconds": self.remaining_budget_seconds,
            "overtime_seconds": self.overtime_seconds,
            "last_poll_timestamp": self.last_poll_timestamp,
            "is_tracked_activity_running": self.is_tracked_activity_running,
            "tracked_activity_name": self.tracked_activity_name,
            "current_session_start_timestamp": self.current_session_start_timestamp,
            "seconds_used_this_session": self.seconds_used_this_session,
            "current_session_mode": self.current_session_mode,
            "overtime_escalation_level": self.overtime_escalation_level,
            "extra_minutes_pending_from_cli": self.extra_minutes_pending_from_cli,
            "gaming_seconds_today": self.gaming_seconds_today,
            "entertainment_seconds_today": self.entertainment_seconds_today,
            "social_seconds_today": self.social_seconds_today,
            "bonus_sites_seconds_today": self.bonus_sites_seconds_today,
            "bonus_apps_seconds_today": self.bonus_apps_seconds_today,
            "other_apps_seconds_today": self.other_apps_seconds_today,
            "session_totals_date": self.session_totals_date,
            "known_steam_game_exes": self.known_steam_game_exes,
        }

    def from_dict(self, data):
        self.remaining_budget_seconds = data.get(
            "remaining_budget_seconds", float(MAX_PLAY_BUDGET)
        )
        self.overtime_seconds = data.get("overtime_seconds", 0.0)
        self.last_poll_timestamp = data.get("last_poll_timestamp", time.time())
        self.is_tracked_activity_running = data.get(
            "is_tracked_activity_running", False
        )
        self.tracked_activity_name = data.get("tracked_activity_name", "")
        self.current_session_start_timestamp = data.get(
            "current_session_start_timestamp", 0.0
        )
        self.seconds_used_this_session = data.get("seconds_used_this_session", 0.0)
        self.current_session_mode = data.get("current_session_mode", "")
        self.overtime_escalation_level = data.get("overtime_escalation_level", 0)
        self.extra_minutes_pending_from_cli = data.get(
            "extra_minutes_pending_from_cli", 0.0
        )
        self.gaming_seconds_today = data.get("gaming_seconds_today", 0.0)
        self.entertainment_seconds_today = data.get(
            "entertainment_seconds_today",
            data.get("watching_seconds_today", 0.0),
        )
        self.social_seconds_today = data.get("social_seconds_today", 0.0)
        self.bonus_sites_seconds_today = data.get(
            "bonus_sites_seconds_today",
            data.get("bonus_seconds_today", 0.0),
        )
        self.bonus_apps_seconds_today = data.get("bonus_apps_seconds_today", 0.0)
        self.other_apps_seconds_today = data.get("other_apps_seconds_today", 0.0)
        self.session_totals_date = data.get(
            "session_totals_date", date.today().isoformat()
        )
        self.known_steam_game_exes = data.get("known_steam_game_exes", [])


def validate_manual_activity_overrides_dict(raw) -> dict:
    if not isinstance(raw, dict):
        return {}
    cleaned = {}
    for k, v in raw.items():
        if not isinstance(k, str) or not isinstance(v, dict):
            continue
        mode = v.get("mode")
        label = v.get("label")
        if (
            not isinstance(mode, str)
            or mode not in _VALID_MANUAL_ACTIVITY_MODES
            or not isinstance(label, str)
        ):
            continue
        cleaned[k.lower()] = {"mode": mode, "label": label}
    return cleaned


def load_manual_activity_overrides() -> dict:
    if not os.path.exists(MANUAL_ACTIVITY_OVERRIDES_FILE):
        return {}
    try:
        with open(MANUAL_ACTIVITY_OVERRIDES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return validate_manual_activity_overrides_dict(data)
    except (json.JSONDecodeError, IOError, OSError, TypeError):
        return {}


def save_manual_activity_overrides(overrides: dict) -> None:
    validated = validate_manual_activity_overrides_dict(overrides)
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(MANUAL_ACTIVITY_OVERRIDES_FILE, "w", encoding="utf-8") as f:
        json.dump(validated, f, indent=2)
        f.write("\n")


def load_state():
    state = AppState()
    if not os.path.exists(STATE_FILE):
        return state

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return state
    except (json.JSONDecodeError, IOError, UnicodeError):
        return state

    legacy = data.pop("manual_activity_overrides", None)

    try:
        state.from_dict(data)
    except (TypeError, ValueError, AttributeError):
        return state

    if legacy is not None:
        if isinstance(legacy, dict):
            migrated = validate_manual_activity_overrides_dict(legacy)
            if migrated:
                current = load_manual_activity_overrides()
                merged = {**migrated, **current}
                save_manual_activity_overrides(merged)
        save_state(state)

    return state


def save_state(state):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state.to_dict(), f, indent=2)


# --- Reset & reload ---
RELOAD_STATE_FLAG = os.path.join(STATE_DIR, ".reload_state")


def reset_state_to_default():
    state = AppState()
    state.last_poll_timestamp = time.time()
    save_state(state)
    _save_extra_data(
        {
            "extra_minutes_pending_from_cli": 0.0,
            "extra_minutes_given_today": 0.0,
            "extra_minutes_date": "",
        }
    )
    save_set_minutes(0.0)
    signal_state_reload()


def check_and_clear_reload_flag():
    if os.path.exists(RELOAD_STATE_FLAG):
        try:
            os.remove(RELOAD_STATE_FLAG)
        except OSError:
            pass
        return True
    return False


def signal_state_reload():
    """Ask a running monitor to reload state from disk on the next poll."""
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(RELOAD_STATE_FLAG, "w"):
        pass


# --- extra.json ---
EXTRA_FILE = os.path.join(STATE_DIR, "extra.json")


def _load_extra_data():
    if not os.path.exists(EXTRA_FILE):
        return {
            "extra_minutes_pending_from_cli": 0.0,
            "extra_minutes_given_today": 0.0,
            "extra_minutes_date": "",
        }
    try:
        with open(EXTRA_FILE, "r") as f:
            data = json.load(f)
        data.setdefault("extra_minutes_pending_from_cli", 0.0)
        data.setdefault("extra_minutes_given_today", 0.0)
        data.setdefault("extra_minutes_date", "")
        return data
    except (json.JSONDecodeError, IOError, ValueError):
        return {
            "extra_minutes_pending_from_cli": 0.0,
            "extra_minutes_given_today": 0.0,
            "extra_minutes_date": "",
        }


def _save_extra_data(data):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(EXTRA_FILE, "w") as f:
        json.dump(data, f, indent=2)


def load_extra_minutes_pending():
    return float(_load_extra_data().get("extra_minutes_pending_from_cli", 0.0))


def save_extra_minutes_pending(minutes):
    data = _load_extra_data()
    data["extra_minutes_pending_from_cli"] = float(minutes)
    _save_extra_data(data)


def load_extra_minutes_given_today():
    data = _load_extra_data()
    today_str = date.today().isoformat()
    if data.get("extra_minutes_date") != today_str:
        return 0.0
    return float(data.get("extra_minutes_given_today", 0.0))


def add_extra_minutes_given_today(minutes):
    data = _load_extra_data()
    today_str = date.today().isoformat()
    if data.get("extra_minutes_date") != today_str:
        data["extra_minutes_given_today"] = 0.0
        data["extra_minutes_date"] = today_str
    data["extra_minutes_given_today"] = float(
        data.get("extra_minutes_given_today", 0.0)
    ) + float(minutes)
    _save_extra_data(data)


# --- set.json ---
SET_FILE = os.path.join(STATE_DIR, "set.json")


def load_set_minutes():
    if not os.path.exists(SET_FILE):
        return 0.0
    try:
        with open(SET_FILE, "r") as f:
            data = json.load(f)
        return float(data.get("set_minutes_pending_from_cli", 0.0))
    except (json.JSONDecodeError, IOError, ValueError):
        return 0.0


def save_set_minutes(minutes):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(SET_FILE, "w") as f:
        json.dump({"set_minutes_pending_from_cli": float(minutes)}, f, indent=2)


# --- Status (CLI + tray) ---
def gather_status_fields(state):

    from hotturkey.utils import (
        format_duration,
    )  # local import to avoid circular dependency

    pending_minutes = load_extra_minutes_pending()
    effective_seconds = max(
        0.0, state.remaining_budget_seconds + (pending_minutes * 60)
    )
    extra_given_today = load_extra_minutes_given_today()

    display_extra_today = int(extra_given_today + max(0.0, pending_minutes))
    return {
        "remaining": format_duration(effective_seconds),
        "overtime": format_duration(getattr(state, "overtime_seconds", 0.0)),
        "total": format_duration(MAX_PLAY_BUDGET),
        "extra_today": display_extra_today,
        "overtime_level": getattr(state, "overtime_escalation_level", 0),
        "gaming_today": format_duration(getattr(state, "gaming_seconds_today", 0.0)),
        "entertainment_today": format_duration(
            getattr(state, "entertainment_seconds_today", 0.0)
        ),
        "social_today": format_duration(getattr(state, "social_seconds_today", 0.0)),
        "bonus_sites_today": format_duration(
            getattr(state, "bonus_sites_seconds_today", 0.0)
        ),
        "bonus_apps_today": format_duration(
            getattr(state, "bonus_apps_seconds_today", 0.0)
        ),
        "other_today": format_duration(getattr(state, "other_apps_seconds_today", 0.0)),
    }


# --- Budget / overtime helpers ---
def apply_extra_seconds(
    budget_before: float, overtime_before: float, extra_seconds: float
):
    budget_after = budget_before
    overtime_after = overtime_before

    if extra_seconds > 0:
        spent_on_debt = min(overtime_before, extra_seconds)
        overtime_after = overtime_before - spent_on_debt
        extra_seconds -= spent_on_debt
        if extra_seconds > 0:
            budget_after = max(0.0, budget_before + extra_seconds)
    elif extra_seconds < 0:
        new_budget = budget_before + extra_seconds
        if new_budget >= 0:
            budget_after = new_budget
        else:
            budget_after = 0.0
            overdraw = -new_budget
            overtime_after = overtime_before + overdraw

    return budget_after, overtime_after


def overtime_base_interval_seconds() -> float:
    return max(
        float(OVERTIME_MIN_INTERVAL_SECONDS),
        0.5 * float(MAX_PLAY_BUDGET),
    )


def overtime_threshold_for_level(target_level: int):
    if target_level <= 0:
        return 0.0
    if target_level == 1:
        return 0.0

    base_interval = overtime_base_interval_seconds()

    cumulative = base_interval
    if target_level == 2:
        return cumulative

    interval = base_interval * float(OVERTIME_INTERVAL_DECAY_FACTOR)
    for _lvl in range(3, target_level + 1):
        if interval < 1.0:
            return None
        cumulative += interval
        interval *= float(OVERTIME_INTERVAL_DECAY_FACTOR)

    return cumulative


def overtime_level_from_debt(overtime_seconds: float) -> int:
    if overtime_seconds <= 0:
        return 0
    base_interval = overtime_base_interval_seconds()
    level = 1
    remaining_for_higher = max(0.0, overtime_seconds - base_interval)
    if remaining_for_higher > 0:
        level = 2
        interval = base_interval * OVERTIME_INTERVAL_DECAY_FACTOR
        while remaining_for_higher >= 1.0 and remaining_for_higher >= interval:
            remaining_for_higher -= interval
            level += 1
            interval *= OVERTIME_INTERVAL_DECAY_FACTOR
            if interval < 1.0:
                break
    return level
