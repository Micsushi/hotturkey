import os

# --- Production values ---
MAX_PLAY_BUDGET = 3600

MAX_EXTRA_MINUTES_PER_DAY = 120
BUDGET_RECOVERY_PER_SECOND_RATIO = 0.5
POLL_INTERVAL = 10
AFK_IDLE_THRESHOLD = 300
# Each overtime popup level comes faster by this factor (0.5 = halves each time: 30, 15, 7.5...)
OVERTIME_INTERVAL_DECAY_FACTOR = 0.5
# Overtime popups won't come faster than this (in seconds)
OVERTIME_MIN_INTERVAL_SECONDS = 60


# --- Testing values ---
# MAX_PLAY_BUDGET = 300
# BUDGET_RECOVERY_PER_SECOND_RATIO = 0.5
# POLL_INTERVAL = 5
# OVERTIME_INTERVAL_DECAY_FACTOR = 0.5
# OVERTIME_MIN_INTERVAL_SECONDS = 5

# State is saved to a hidden .hotturkey folder in the user's home directory
# (e.g. C:\Users\sushi\.hotturkey\state.json) so it survives restarts and
# works no matter where you run the program from.
STATE_DIR = os.path.join(os.path.expanduser("~"), ".hotturkey")
STATE_FILE = os.path.join(STATE_DIR, "state.json")
LOG_FILE = os.path.join(STATE_DIR, "hotturkey.log")

STEAM_PROCESS_NAME = "steam.exe"

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

TRACKED_BROWSERS = ["brave", "chrome", "firefox", "edge"]

TRACKED_SITES = ["youtube", "watchseries", "hianime"]

BONUS_SITES = [
    "kwiziq",  
    "leetcode", 
]

BONUS_RECOVERY_MULTIPLIER = 2.0