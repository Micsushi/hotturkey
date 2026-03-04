# config.py -- All tunable settings in one place.
# Change values here to adjust how the app behaves.

import os

# --- Production values ---
# # How many seconds of play/watch time you get (3600 = 1 hour)
# MAX_PLAY_BUDGET_SECONDS = 3600
# # How fast budget recovers when idle (0.5 = you need 2x the idle time to recover play time)
# BUDGET_RECOVERY_PER_SECOND_IDLE = 0.5
# # How often the app checks if a game or site is focused (in seconds)
# DETECTION_POLL_INTERVAL_SECONDS = 5
# # A quick flash reminder appears after this many seconds of play (1800 = 30 min)
# GENTLE_REMINDER_AFTER_SECONDS = 1800
# # How long the flash reminder stays on screen (in seconds)
# GENTLE_REMINDER_VISIBLE_SECONDS = 2
# # After budget hits 0, wait this long before the first fullscreen popup (1800 = 30 min)
# FIRST_OVERTIME_POPUP_DELAY_SECONDS = 1800
# # Each overtime popup comes faster by this factor (0.5 = halves each time: 30, 15, 7.5...)
# OVERTIME_INTERVAL_DECAY_FACTOR = 0.5
# # Overtime popups won't come faster than this (in seconds)
# OVERTIME_MIN_INTERVAL_SECONDS = 15

# --- Testing values (swap back to production when done) ---
MAX_PLAY_BUDGET_SECONDS = 30
BUDGET_RECOVERY_PER_SECOND_IDLE = 0.5
DETECTION_POLL_INTERVAL_SECONDS = 5
GENTLE_REMINDER_AFTER_SECONDS = 10
GENTLE_REMINDER_VISIBLE_SECONDS = 2
FIRST_OVERTIME_POPUP_DELAY_SECONDS = 15
OVERTIME_INTERVAL_DECAY_FACTOR = 0.5
OVERTIME_MIN_INTERVAL_SECONDS = 5

# State is saved to a hidden .hotturkey folder in the user's home directory
# (e.g. C:\Users\sushi\.hotturkey\state.json) so it survives restarts and
# works no matter where you run the program from.
STATE_DIR = os.path.join(os.path.expanduser("~"), ".hotturkey")
STATE_FILE = os.path.join(STATE_DIR, "state.json")
LOG_FILE = os.path.join(STATE_DIR, "hotturkey.log")

# The Steam client process name
STEAM_PROCESS_NAME = "steam.exe"

# Steam background processes to ignore (these are not games)
STEAM_HELPER_PROCESS_NAMES = {
    "steam.exe",
    "steamservice.exe",
    "steamwebhelper.exe",
    "gameoverlayui.exe",
    "steamerrorreporter.exe",
    "streaming_client.exe",
    "steamvr_room_setup.exe",
    "vrmonitor.exe",
    "vrserver.exe",
    "vrcompositor.exe",
}

# Browser names to look for in window titles (add more if needed)
TRACKED_BROWSERS = ["brave", "chrome", "firefox", "edge"]

# Site names to look for in window titles (add more if needed)
TRACKED_SITES = ["youtube"]
