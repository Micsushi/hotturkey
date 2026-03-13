import os

# Configurable values

# Total daily play budget in seconds (default: 1 hour).
MAX_PLAY_BUDGET = 3600
# Max extra minutes that can be granted via CLI per day.
MAX_EXTRA_MINUTES_PER_DAY = 120
# Fraction of a second recovered per idle/bonus second (0.5 = 1s idle -> 0.5s back).
BUDGET_RECOVERY_PER_SECOND_RATIO = 0.5
# Seconds between monitor polls.
POLL_INTERVAL = 10
# Seconds of no input before we treat the user as AFK.
AFK_IDLE_THRESHOLD = 300
# Each overtime popup level comes faster by this factor (0.5 = halves each time: 30, 15, 7.5...).
OVERTIME_INTERVAL_DECAY_FACTOR = 0.5
# Minimum interval between overtime popups in seconds (never faster than this).
OVERTIME_MIN_INTERVAL_SECONDS = 60
# How much faster budget recovers on bonus sites vs normal idle (3x here).
BONUS_RECOVERY_MULTIPLIER = 3.0
# Good desktop apps that earn bonus time (e.g. coding, study tools) recover more slowly.
BONUS_APPS_RECOVERY_MULTIPLIER = 2.0
# Social media consumes budget more slowly than games/videos (0.5 = half speed).
SOCIAL_CONSUME_RATIO = 0.5

# Browser / app detection
TRACKED_BROWSERS = ["brave", "chrome", "firefox", "edge"]
TRACKED_SITES = ["youtube", "watchseries", "hianime", "twitch", "reddit", "netflix", "9animetv"]
BONUS_SITES = ["kwiziq", "leetcode", "github"]
BONUS_APPS = ["cursor", "vscode", "terminal", "command prompt"]
SOCIAL_APPS_OR_SITES = ["whatsapp", "discord"]


# --- Testing values ---
# MAX_PLAY_BUDGET = 300
# MAX_EXTRA_MINUTES_PER_DAY = 120
# BUDGET_RECOVERY_PER_SECOND_RATIO = 0.5
# POLL_INTERVAL = 1
# AFK_IDLE_THRESHOLD= 300
# OVERTIME_INTERVAL_DECAY_FACTOR = 0.5
# OVERTIME_MIN_INTERVAL_SECONDS = 5
# BONUS_RECOVERY_MULTIPLIER = 5.0
# BONUS_APPS_RECOVERY_MULTIPLIER = 2.0
# SOCIAL_CONSUME_RATIO = 0.5


# State is saved to a hidden .hotturkey folder in the user's home directory
# (e.g. C:\Users\sushi\.hotturkey\state.json) so it survives restarts and
# works no matter where you run the program from.
STATE_DIR = os.path.join(os.path.expanduser("~"), ".hotturkey")
STATE_FILE = os.path.join(STATE_DIR, "state.json")
LOG_FILE = os.path.join(STATE_DIR, "hotturkey.log")

# Small text file that controls the log level (INFO/DEBUG/etc) so the CLI
# can toggle verbosity without editing code.
LOG_LEVEL_FILE = os.path.join(STATE_DIR, "loglevel.txt")

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


