# state.py -- Holds all the data the app needs to remember, and saves/loads it as JSON.
# The AppState object gets passed around between the monitor, popup, and tray modules.

import json
import os
import time

from hotturkey.config import STATE_DIR, STATE_FILE, MAX_PLAY_BUDGET_SECONDS


class AppState:
    """Holds everything the app needs to track between poll cycles and across restarts."""

    def __init__(self):
        # How many seconds of play time are left
        self.remaining_budget_seconds = float(MAX_PLAY_BUDGET_SECONDS)

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

        # Whether the gentle 30-min flash reminder has already been shown this session
        self.has_shown_gentle_reminder = False

        # How many overtime popups have fired (controls the halving interval)
        self.overtime_escalation_level = 0

        # When the next overtime popup should appear (unix timestamp)
        self.overtime_next_popup_timestamp = 0.0

        # Extra minutes added via "hotturkey extra X" CLI, waiting to be picked up
        self.extra_minutes_pending_from_cli = 0.0

    def to_dict(self):
        """Convert this object to a plain dictionary so it can be saved as JSON."""
        return {
            "remaining_budget_seconds": self.remaining_budget_seconds,
            "last_poll_timestamp": self.last_poll_timestamp,
            "is_tracked_activity_running": self.is_tracked_activity_running,
            "tracked_activity_name": self.tracked_activity_name,
            "current_session_start_timestamp": self.current_session_start_timestamp,
            "seconds_used_this_session": self.seconds_used_this_session,
            "has_shown_gentle_reminder": self.has_shown_gentle_reminder,
            "overtime_escalation_level": self.overtime_escalation_level,
            "overtime_next_popup_timestamp": self.overtime_next_popup_timestamp,
            "extra_minutes_pending_from_cli": self.extra_minutes_pending_from_cli,
        }

    def from_dict(self, data):
        """Restore this object's fields from a dictionary (loaded from JSON).
        Uses defaults if any key is missing, so old state files still work."""
        self.remaining_budget_seconds = data.get("remaining_budget_seconds", float(MAX_PLAY_BUDGET_SECONDS))
        self.last_poll_timestamp = data.get("last_poll_timestamp", time.time())
        self.is_tracked_activity_running = data.get("is_tracked_activity_running", False)
        self.tracked_activity_name = data.get("tracked_activity_name", "")
        self.current_session_start_timestamp = data.get("current_session_start_timestamp", 0.0)
        self.seconds_used_this_session = data.get("seconds_used_this_session", 0.0)
        self.has_shown_gentle_reminder = data.get("has_shown_gentle_reminder", False)
        self.overtime_escalation_level = data.get("overtime_escalation_level", 0)
        self.overtime_next_popup_timestamp = data.get("overtime_next_popup_timestamp", 0.0)
        self.extra_minutes_pending_from_cli = data.get("extra_minutes_pending_from_cli", 0.0)


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


# --- Extra-time helpers for CLI <-> monitor coordination ---

EXTRA_FILE = os.path.join(STATE_DIR, "extra.json")


def load_extra_minutes_pending():
    """Return minutes of extra time requested via the CLI but not yet applied.
    Stored separately from state.json so CLI can work whether the app is running or not."""
    if not os.path.exists(EXTRA_FILE):
        return 0.0
    try:
        with open(EXTRA_FILE, "r") as f:
            data = json.load(f)
        return float(data.get("extra_minutes_pending_from_cli", 0.0))
    except (json.JSONDecodeError, IOError, ValueError):
        return 0.0


def save_extra_minutes_pending(minutes):
    """Persist pending extra minutes so the running app (or next run) can pick them up."""
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(EXTRA_FILE, "w") as f:
        json.dump({"extra_minutes_pending_from_cli": float(minutes)}, f, indent=2)
