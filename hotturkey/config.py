import os

# --- Production values ---
# How many seconds of play/watch time you get (3600 = 1 hour)
MAX_PLAY_BUDGET_SECONDS = 3600
# How fast budget recovers when idle (0.5 = you need 2x the idle time to recover play time)
BUDGET_RECOVERY_PER_SECOND_IDLE = 0.5
# How often the app checks if a game or site is focused (in seconds)
DETECTION_POLL_INTERVAL_SECONDS = 10
# Each overtime popup level comes faster by this factor (0.5 = halves each time: 30, 15, 7.5...)
OVERTIME_INTERVAL_DECAY_FACTOR = 0.5
# Overtime popups won't come faster than this (in seconds)
OVERTIME_MIN_INTERVAL_SECONDS = 60

# If there is no keyboard or mouse input for this many seconds, the user is
# considered AFK. While AFK, budget neither recovers nor is consumed unless a
# tracked activity (YouTube / game) is focused.
AFK_IDLE_THRESHOLD_SECONDS = 300

# --- Testing values (swap back to production when done) ---
# MAX_PLAY_BUDGET_SECONDS = 300
# BUDGET_RECOVERY_PER_SECOND_IDLE = 0.5
# DETECTION_POLL_INTERVAL_SECONDS = 5
# OVERTIME_INTERVAL_DECAY_FACTOR = 0.5
# OVERTIME_MIN_INTERVAL_SECONDS = 5

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
    "gameoverlayui64.exe",
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
TRACKED_SITES = ["youtube", "watchseries", "hianime"]

# Sites that count as "bonus" / productive time. These are simple keywords that
# are matched against the window title in lowercase (similar to TRACKED_SITES).
# When these are focused, HotTurkey recovers budget faster than normal idle
# instead of consuming it.
BONUS_SITES = [
    "kwiziq",    # french.kwiziq.com
    "leetcode",  # leetcode.com
]

# How much faster budget recovers on BONUS_SITES compared to normal idle.
# For example, 2.0 means twice as fast as idle.
BONUS_RECOVERY_MULTIPLIER = 2.0