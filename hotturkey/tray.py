# tray.py -- The system tray icon that sits near your clock.
# Shows a colored circle (green/yellow/orange/red) based on remaining budget.
# Hover to see time left. Right-click for Status, Show logs, or Quit.

import subprocess

import pystray
from PIL import Image, ImageDraw

from hotturkey.config import MAX_PLAY_BUDGET, MAX_EXTRA_MINUTES_PER_DAY, LOG_FILE
from hotturkey.logger import log
from hotturkey.state import load_extra_minutes_given_today


# Module-level references so update_tray_icon can reach the icon and state
_icon = None
_state_ref = None
_quit_callback = None


def _build_icon_image(budget_seconds):
    """Draw a 64x64 colored circle.
    Color depends on the *percentage* of budget left so it behaves consistently
    even when MAX_PLAY_BUDGET is changed for testing:
      - green  : > 50% remaining
      - yellow : 25–50% remaining
      - orange : 0–25% remaining
      - red    : 0 or below"""
    if MAX_PLAY_BUDGET <= 0:
        ratio = 0.0
    else:
        ratio = max(0.0, min(1.0, budget_seconds / float(MAX_PLAY_BUDGET)))

    if ratio <= 0.0:
        color = "#DC2626"  # red
    elif ratio < 0.25:
        color = "#F97316"  # orange
    elif ratio < 0.5:
        color = "#EAB308"  # yellow
    else:
        color = "#22C55E"  # green

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
    overtime = _format_time(getattr(s, "overtime_seconds", 0.0))
    total = _format_time(MAX_PLAY_BUDGET)
    extra_today = int(load_extra_minutes_given_today())
    activity = s.tracked_activity_name if s.is_tracked_activity_running else "None"
    session = _format_time(s.seconds_used_this_session) if s.is_tracked_activity_running else "N/A"
    msg = (
        f"HotTurkey Status"
        f" & echo."
        f" & echo   Budget:      {remaining} / {total}"
        f" & echo   Overtime:    {overtime}"
        f" & echo   Extra today: {extra_today} / {MAX_EXTRA_MINUTES_PER_DAY} min"
        f" & echo   Activity:    {activity}"
        f" & echo   Session:     {session}"
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
    log.info("[COMMAND] quit: user quit from tray.")
    if _quit_callback:
        _quit_callback()
    icon.stop()


def create_tray_icon(quit_callback=None):
    """Build the tray icon with a right-click menu. Returns the icon object.
    quit_callback is called when the user clicks Quit, so run.py can stop its loop."""
    global _icon, _quit_callback
    _quit_callback = quit_callback
    image = _build_icon_image(MAX_PLAY_BUDGET)
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
    overtime = getattr(state, "overtime_seconds", 0.0)
    debt_str = _format_time(overtime)
    extra_today = int(load_extra_minutes_given_today())
    extra_str = f"Extra: {extra_today}/{MAX_EXTRA_MINUTES_PER_DAY} today"
    debt_part = f" | Debt: {debt_str}" if overtime > 0 else ""
    if state.is_tracked_activity_running:
        _icon.title = f"HotTurkey: {remaining} left ({state.tracked_activity_name}) | {extra_str}{debt_part}"
    else:
        _icon.title = f"HotTurkey: {remaining} remaining | {extra_str}{debt_part}"
