import os

MAX_PLAY_BUDGET_SECONDS = 3600
BUDGET_RECOVERY_PER_SECOND_IDLE = 0.5

DETECTION_POLL_INTERVAL_SECONDS = 5

GENTLE_REMINDER_AFTER_SECONDS = 1800
GENTLE_REMINDER_VISIBLE_SECONDS = 2

FIRST_OVERTIME_POPUP_DELAY_SECONDS = 1800
OVERTIME_INTERVAL_DECAY_FACTOR = 0.5
OVERTIME_MIN_INTERVAL_SECONDS = 15

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
    "steamerrorreporter.exe",
    "streaming_client.exe",
    "steamvr_room_setup.exe",
    "vrmonitor.exe",
    "vrserver.exe",
    "vrcompositor.exe",
}

TRACKED_BROWSERS = ["brave", "chrome", "firefox", "edge"]
TRACKED_SITES = ["youtube"]
