import os
from datetime import date

# Configurable values

# Total daily play budget in seconds (default: 3 hour).
MAX_PLAY_BUDGET = 3600*3
# Max extra minutes that can be granted via CLI per day.
MAX_EXTRA_MINUTES_PER_DAY = 60
# Days of the week that get bonus extra-time cap (double). Monday=0, Sunday=6.
# Tue, Thu, Sat, Sun get double the daily extra cap.
EXTRA_TIME_BONUS_DAYS = (4, 5, 6)
EXTRA_TIME_BONUS_DAY_MULTIPLIER = 2.0
# Fraction of a second recovered per idle/bonus second (0.5 = 1s idle -> 0.5s back).
BUDGET_RECOVERY_PER_SECOND_RATIO = 0.5
# Seconds between monitor polls.
POLL_INTERVAL = 10
# If the process did not run for longer than this (sleep, suspend, hang), only one
# POLL_INTERVAL of wall time is applied to budget consume/recovery on the next tick.
# Prevents a huge credit after AFK + resume when polls were not running.
BUDGET_ELAPSED_GAP_CLAMP_THRESHOLD_SECONDS = 60.0
# Seconds of no input before we treat the user as AFK.
AFK_IDLE_THRESHOLD = 300
# Each overtime popup level comes faster by this factor (0.5 = halves each time: 30, 15, 7.5...).
OVERTIME_INTERVAL_DECAY_FACTOR = 0.5
# Minimum interval between overtime popups in seconds (never faster than this).
OVERTIME_MIN_INTERVAL_SECONDS = 60
# How much faster budget recovers on bonus sites vs normal idle (3x here).
BONUS_RECOVERY_MULTIPLIER = 2.0
# Good desktop apps that earn bonus time (e.g. coding, study tools) recover more slowly.
BONUS_APPS_RECOVERY_MULTIPLIER = 1.5
# Social media consumes budget more slowly than games/videos (0.5 = half speed).
SOCIAL_CONSUME_RATIO = 0.5

# Browser / app detection
TRACKED_BROWSERS = ["brave", "chrome", "firefox", "edge"]
TRACKED_SITES = [
    "youtube",
    "watchseries",
    "hianime",
    "twitch",
    "reddit",
    "netflix",
    "9anime",
    "9animetv",
    # Some watch sites (e.g. watchseries.mn) don't include the brand/domain
    # in the browser tab title, but do include "HD free".
    "hd free",
    "gogoanime",
]
BONUS_SITES = ["kwiziq", "leetcode", "github"]
BONUS_APPS = ["cursor", "vscode", "visual studio code", "terminal", "command prompt", "zed", "antigravity"]
SOCIAL_APPS_OR_SITES = ["whatsapp", "discord"]


def get_effective_max_extra_minutes_per_day(day=None):
    """Return the max extra minutes allowed today. On EXTRA_TIME_BONUS_DAYS (Tue, Thu, Sat, Sun) it's doubled."""
    d = day if day is not None else date.today()
    if d.weekday() in EXTRA_TIME_BONUS_DAYS:
        return int(MAX_EXTRA_MINUTES_PER_DAY * EXTRA_TIME_BONUS_DAY_MULTIPLIER)
    return MAX_EXTRA_MINUTES_PER_DAY


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
HISTORY_DB = os.path.join(STATE_DIR, "history.db")
LOG_FILE = os.path.join(STATE_DIR, "hotturkey.log")

# Small text file that controls the log level (INFO/DEBUG/etc) so the CLI
# can toggle verbosity without editing code.
LOG_LEVEL_FILE = os.path.join(STATE_DIR, "loglevel.txt")

STEAM_PROCESS_NAME = "steam.exe"

# Exe names (lowercase) that are always counted as gaming, regardless of Steam
# ancestry. Use this for games that launch through a non-Steam intermediary
# (e.g. a publisher launcher that breaks the process parent chain).
# Example: publisher clients that detach from Steam: Arc Raiders runs as Pioneergame.exe
KNOWN_GAME_EXECUTABLES: set = {"pioneergame.exe"}

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
