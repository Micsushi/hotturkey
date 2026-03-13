# state.py -- Holds all the data the app needs to remember, and saves/loads it as JSON.
# The AppState object gets passed around between the monitor, popup, and tray modules.

import json
import os
import time
from datetime import date

from hotturkey.config import (
    STATE_DIR,
    STATE_FILE,
    MAX_PLAY_BUDGET,
    OVERTIME_INTERVAL_DECAY_FACTOR,
    OVERTIME_MIN_INTERVAL_SECONDS,
)


class AppState:
    """Holds everything the app needs to track between poll cycles and across restarts."""

    def __init__(self):
        # How many seconds of play time are left
        self.remaining_budget_seconds = float(MAX_PLAY_BUDGET)

        # How many seconds have been spent *after* the budget hit 0.
        # This is tracked separately so we can show "overtime used" and
        # pay it back before refilling normal budget.
        self.overtime_seconds = 0.0

        # When the last poll cycle ran (used to calculate time between checks)
        self.last_poll_timestamp = time.time()

        # Whether a game or tracked site is currently focused
        self.is_tracked_activity_running = False

        # What is being tracked right now, e.g. "Steam: game.exe" or "YouTube (Brave)"
        self.tracked_activity_name = ""

        # When the current play/watch session started
        self.current_session_start_timestamp = 0.0

        # Total seconds used in the current session
        self.seconds_used_this_session = 0.0

        # Mode for the current session: 'consume' (gaming/YouTube) or 'bonus'
        self.current_session_mode = ""

        # How many overtime popups have fired (controls the halving interval)
        self.overtime_escalation_level = 0

        # When the next overtime popup should appear (unix timestamp)
        self.overtime_next_popup_timestamp = 0.0

        # Extra minutes added via "hotturkey extra X" CLI, waiting to be picked up
        self.extra_minutes_pending_from_cli = 0.0

        # Totals for how much time was spent today in different modes.
        # These reset when the date changes.
        self.gaming_seconds_today = 0.0
        self.watching_seconds_today = 0.0
        self.bonus_seconds_today = 0.0
        self.other_apps_seconds_today = 0.0
        self.session_totals_date = date.today().isoformat()

        # Steam game executables we've learned across runs. This lets the app
        # remember which exes should always be treated as Steam games, even if
        # their process tree changes or the launcher is missed once.
        self.known_steam_game_exes = []

    def to_dict(self):
        """Convert this object to a plain dictionary so it can be saved as JSON."""
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
            "overtime_next_popup_timestamp": self.overtime_next_popup_timestamp,
            "extra_minutes_pending_from_cli": self.extra_minutes_pending_from_cli,
            "gaming_seconds_today": self.gaming_seconds_today,
            "watching_seconds_today": self.watching_seconds_today,
            "bonus_seconds_today": self.bonus_seconds_today,
            "other_apps_seconds_today": self.other_apps_seconds_today,
            "session_totals_date": self.session_totals_date,
            "known_steam_game_exes": self.known_steam_game_exes,
        }

    def from_dict(self, data):
        """Restore this object's fields from a dictionary (loaded from JSON).
        Uses defaults if any key is missing, so old state files still work."""
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
        self.overtime_next_popup_timestamp = data.get(
            "overtime_next_popup_timestamp", 0.0
        )
        self.extra_minutes_pending_from_cli = data.get(
            "extra_minutes_pending_from_cli", 0.0
        )
        # Backwards compatibility: older state files may only have consume_seconds_today.
        consume_fallback = data.get("consume_seconds_today", 0.0)
        self.gaming_seconds_today = data.get("gaming_seconds_today", consume_fallback)
        self.watching_seconds_today = data.get("watching_seconds_today", 0.0)
        self.bonus_seconds_today = data.get("bonus_seconds_today", 0.0)
        self.other_apps_seconds_today = data.get("other_apps_seconds_today", 0.0)
        self.session_totals_date = data.get(
            "session_totals_date", date.today().isoformat()
        )
        self.known_steam_game_exes = data.get("known_steam_game_exes", [])


def load_state():
    """Read saved state from disk. If the file doesn't exist or is broken, return fresh defaults."""
    state = AppState()
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                state.from_dict(json.load(f))
        except (json.JSONDecodeError, IOError):
            pass
    return state


def save_state(state):
    """Write current state to disk so it survives restarts.
    Creates the .hotturkey folder if it doesn't exist yet."""
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state.to_dict(), f, indent=2)


RELOAD_STATE_FLAG = os.path.join(STATE_DIR, ".reload_state")


def reset_state_to_default():
    """Reset all state to default: full budget, zero overtime, extra today cleared,
    pending extra/set cleared. Works whether the app is running or not.
    If the app is running, it will reload state on the next poll."""
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
    # Signal running monitor to reload state from disk on next poll
    with open(RELOAD_STATE_FLAG, "w"):
        pass


def check_and_clear_reload_flag():
    """If a reload was requested (e.g. after reset), remove the flag and return True."""
    if os.path.exists(RELOAD_STATE_FLAG):
        try:
            os.remove(RELOAD_STATE_FLAG)
        except OSError:
            pass
        return True
    return False


# --- Extra-time helpers for CLI <-> monitor coordination ---

EXTRA_FILE = os.path.join(STATE_DIR, "extra.json")


def _load_extra_data():
    """Load full extra.json; return dict with defaults for missing keys."""
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
    """Write full extra.json."""
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(EXTRA_FILE, "w") as f:
        json.dump(data, f, indent=2)


def load_extra_minutes_pending():
    """Return minutes of extra time requested via the CLI but not yet applied.
    Stored separately from state.json so CLI can work whether the app is running or not.
    """
    return float(_load_extra_data().get("extra_minutes_pending_from_cli", 0.0))


def save_extra_minutes_pending(minutes):
    """Persist pending extra minutes so the running app (or next run) can pick them up."""
    data = _load_extra_data()
    data["extra_minutes_pending_from_cli"] = float(minutes)
    _save_extra_data(data)


def load_extra_minutes_given_today():
    """Return how many extra minutes have been given today (applied by the monitor).
    Returns 0 if the stored date is not today (e.g. new day)."""
    data = _load_extra_data()
    today_str = date.today().isoformat()
    if data.get("extra_minutes_date") != today_str:
        return 0.0
    return float(data.get("extra_minutes_given_today", 0.0))


def add_extra_minutes_given_today(minutes):
    """Record that we applied this many positive extra minutes today. Call from monitor when applying."""
    data = _load_extra_data()
    today_str = date.today().isoformat()
    if data.get("extra_minutes_date") != today_str:
        data["extra_minutes_given_today"] = 0.0
        data["extra_minutes_date"] = today_str
    data["extra_minutes_given_today"] = float(
        data.get("extra_minutes_given_today", 0.0)
    ) + float(minutes)
    _save_extra_data(data)


# --- Set-time helpers for CLI <-> monitor coordination ---

SET_FILE = os.path.join(STATE_DIR, "set.json")


def load_set_minutes():
    """Return minutes requested via the 'set' CLI (can be positive or negative).

    Positive value means 'set budget to this many minutes remaining and clear overtime'.
    Negative value means 'set overtime debt to this many minutes (budget 0)'.
    Zero means 'no pending set command'.
    """
    if not os.path.exists(SET_FILE):
        return 0.0
    try:
        with open(SET_FILE, "r") as f:
            data = json.load(f)
        return float(data.get("set_minutes_pending_from_cli", 0.0))
    except (json.JSONDecodeError, IOError, ValueError):
        return 0.0


def save_set_minutes(minutes):
    """Persist pending set minutes so the running app (or next run) can pick them up."""
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(SET_FILE, "w") as f:
        json.dump({"set_minutes_pending_from_cli": float(minutes)}, f, indent=2)


def gather_status_fields(state):
    """Build a dict of all formatted status values from a state object.

    Used by both the CLI and the tray popup so the data logic lives in one place.
    """
    from hotturkey.utils import format_mmss  # local import to avoid circular dependency

    pending_minutes = load_extra_minutes_pending()
    effective_seconds = max(
        0.0, state.remaining_budget_seconds + (pending_minutes * 60)
    )
    return {
        "remaining": format_mmss(effective_seconds),
        "overtime": format_mmss(getattr(state, "overtime_seconds", 0.0)),
        "total": format_mmss(MAX_PLAY_BUDGET),
        "extra_today": int(load_extra_minutes_given_today()),
        "overtime_level": getattr(state, "overtime_escalation_level", 0),
        "gaming_today": format_mmss(getattr(state, "gaming_seconds_today", 0.0)),
        "watching_today": format_mmss(getattr(state, "watching_seconds_today", 0.0)),
        "bonus_today": format_mmss(getattr(state, "bonus_seconds_today", 0.0)),
        "other_today": format_mmss(getattr(state, "other_apps_seconds_today", 0.0)),
    }


def apply_extra_seconds(
    budget_before: float, overtime_before: float, extra_seconds: float
):
    """Apply extra seconds to budget/overtime and return (budget_after, overtime_after).

    Positive extra:
      - First clears overtime, then adds any leftover to budget.
    Negative extra:
      - First subtracts from budget, then any remainder becomes overtime.
    """
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


def overtime_level_from_debt(overtime_seconds: float) -> int:
    """Compute overtime level (1, 2, 3, ...) from current overtime debt."""
    if overtime_seconds <= 0:
        return 0
    base_interval = max(
        float(OVERTIME_MIN_INTERVAL_SECONDS),
        0.5 * float(MAX_PLAY_BUDGET),
    )
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
