import psutil
import win32gui
import win32process

from hotturkey.config import (
    STEAM_PROCESS_NAME,
    STEAM_HELPER_PROCESS_NAMES,
    TRACKED_BROWSERS,
    TRACKED_SITES,
)
from hotturkey.logger import log


def get_foreground_window_info():
    """Return (pid, title) of the currently focused window."""
    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return 0, ""
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    title = win32gui.GetWindowText(hwnd)
    return pid, title


def get_steam_game_pids():
    """Find all non-helper child process PIDs of steam.exe."""
    game_pids = {}
    for process in psutil.process_iter(["name", "pid"]):
        try:
            if process.info["name"] and process.info["name"].lower() == STEAM_PROCESS_NAME:
                for child in process.children(recursive=True):
                    try:
                        child_name = child.name().lower()
                        if child_name not in STEAM_HELPER_PROCESS_NAMES:
                            game_pids[child.pid] = child.name()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return game_pids


def detect_steam_game_focused(foreground_pid):
    """Check if the focused window belongs to a Steam game.
    Returns the game process name or empty string."""
    game_pids = get_steam_game_pids()
    if foreground_pid in game_pids:
        return game_pids[foreground_pid]
    return ""


def detect_tracked_site_focused(foreground_title):
    """Check if the focused window is a tracked site in a tracked browser.
    Returns a label like 'YouTube (Brave)' or empty string."""
    title_lower = foreground_title.lower()
    for site in TRACKED_SITES:
        if site in title_lower:
            for browser in TRACKED_BROWSERS:
                if browser in title_lower:
                    return f"{site.title()} ({browser.title()})"
    return ""


def detect_tracked_activity():
    """Run all detections against the currently focused window.
    Returns (is_active, source_name)."""
    foreground_pid, foreground_title = get_foreground_window_info()

    steam_game_name = detect_steam_game_focused(foreground_pid)
    if steam_game_name:
        log.info(f"[GAMING] {steam_game_name} is focused")
        return True, f"Steam: {steam_game_name}"

    browser_match = detect_tracked_site_focused(foreground_title)
    if browser_match:
        log.info(f"[WATCHING] {browser_match} is focused")
        return True, browser_match

    log.debug("[IDLE] No tracked activity focused")
    return False, ""
