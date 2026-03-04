# tray.py -- The system tray icon that sits near your clock.
# Shows a colored circle (green/yellow/orange/red) based on remaining budget.
# Hover to see time left. Right-click for Status, Show logs, or Quit.

import subprocess

import pystray
from PIL import Image, ImageDraw

from hotturkey.config import MAX_PLAY_BUDGET_SECONDS, LOG_FILE
from hotturkey.logger import log


# Module-level references so update_tray_icon can reach the icon and state
_icon = None
_state_ref = None
_quit_callback = None


def _build_icon_image(budget_seconds):
    """Draw a 64x64 colored circle. Color depends on how much budget is left:
    green = plenty, yellow = getting low, orange = almost out, red = depleted."""
    if budget_seconds <= 0:
        color = "#DC2626"
    elif budget_seconds < 600:
        color = "#F97316"
    elif budget_seconds < 1800:
        color = "#EAB308"
    else:
        color = "#22C55E"

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, 60, 60], fill=color)
    return img


def _format_time(seconds):
    """Turn seconds into mm:ss string."""
    minutes = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{minutes}:{secs:02d}"


def _on_status(icon, item):
    """Right-click menu handler: opens a small terminal showing current budget info."""
    if _state_ref is None:
        return
    s = _state_ref
    remaining = _format_time(s.remaining_budget_seconds)
    total = _format_time(MAX_PLAY_BUDGET_SECONDS)
    activity = s.tracked_activity_name if s.is_tracked_activity_running else "None"
    session = _format_time(s.seconds_used_this_session) if s.is_tracked_activity_running else "N/A"
    msg = (
        f"HotTurkey Status"
        f" & echo."
        f" & echo   Budget: {remaining} / {total}"
        f" & echo   Activity: {activity}"
        f" & echo   Session: {session}"
        f" & echo."
    )
    subprocess.Popen(
        ["cmd", "/c", f"echo. & echo  {msg} & pause"],
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )


def _on_show_logs(icon, item):
    """Right-click menu handler: opens a terminal that tails the log file in real time."""
    log_path = LOG_FILE.replace("'", "''")
    subprocess.Popen(
        [
            "powershell",
            "-NoExit",
            "-Command",
            f"Get-Content '{log_path}' -Wait -Tail 50",
        ],
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )


def _on_quit(icon, item):
    """Right-click menu handler: shuts down the app."""
    log.info("[TRAY] Quit requested")
    if _quit_callback:
        _quit_callback()
    icon.stop()


def create_tray_icon(quit_callback=None):
    """Build the tray icon with a right-click menu. Returns the icon object.
    quit_callback is called when the user clicks Quit, so run.py can stop its loop."""
    global _icon, _quit_callback
    _quit_callback = quit_callback
    image = _build_icon_image(MAX_PLAY_BUDGET_SECONDS)
    menu = pystray.Menu(
        pystray.MenuItem("Status", _on_status),
        pystray.MenuItem("Show logs", _on_show_logs),
        pystray.MenuItem("Quit", _on_quit),
    )
    _icon = pystray.Icon("HotTurkey", image, "HotTurkey", menu)
    return _icon


def update_tray_icon(state):
    """Called every poll cycle to refresh the icon color and hover tooltip."""
    global _state_ref
    _state_ref = state
    if _icon is None:
        return
    _icon.icon = _build_icon_image(state.remaining_budget_seconds)
    remaining = _format_time(state.remaining_budget_seconds)
    if state.is_tracked_activity_running:
        _icon.title = f"HotTurkey: {remaining} left ({state.tracked_activity_name})"
    else:
        _icon.title = f"HotTurkey: {remaining} remaining"
