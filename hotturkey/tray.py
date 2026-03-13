# tray.py -- The system tray icon that sits near your clock.
# Shows a colored circle (green/yellow/orange/red) based on remaining budget.
# Hover to see time left. Right-click for Status, Show logs, or Quit.

import subprocess

import pystray
from PIL import Image, ImageDraw

from hotturkey.config import MAX_PLAY_BUDGET, MAX_EXTRA_MINUTES_PER_DAY, LOG_FILE
from hotturkey.logger import log
from hotturkey.state import (
    load_extra_minutes_given_today,
    gather_status_fields,
)
from hotturkey.utils import format_mmss

# Module-level references so update_tray_icon can reach the icon and state
_icon = None
_state_ref = None
_quit_callback = None


def _build_icon_image(budget_seconds):
    """Draw a 64x64 colored circle.
    Color depends on the *percentage* of budget left so it behaves consistently
    even when MAX_PLAY_BUDGET is changed for testing:
      - white  : 100% (or more) remaining
      - green  : 50–100% remaining
      - yellow : 25–50% remaining
      - orange : 0–25% remaining
      - red    : 0 or below"""
    if MAX_PLAY_BUDGET <= 0:
        ratio = 0.0
    else:
        ratio = budget_seconds / float(MAX_PLAY_BUDGET)

    if ratio <= 0.0:
        color = "#DC2626"  # red
    elif ratio < 0.25:
        color = "#F97316"  # orange
    elif ratio < 0.5:
        color = "#EAB308"  # yellow
    elif ratio < 1.0:
        color = "#22C55E"  # green
    else:
        color = "#FFFFFF"  # white (full budget)

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, 60, 60], fill=color)
    return img


def _on_status(icon, item):  # pylint: disable=unused-argument
    """Right-click menu handler: opens a small terminal showing current budget info."""
    if _state_ref is None:
        return
    s = gather_status_fields(_state_ref)
    msg = (
        "HotTurkey Status"
        f" & echo."
        f" & echo   Budget:        {s['remaining']} / {s['total']}"
        f" & echo   Overtime:      {s['overtime']}"
        f" & echo   Overtime lvl:  {s['overtime_level']}"
        f" & echo   Extra today:   {s['extra_today']} / {MAX_EXTRA_MINUTES_PER_DAY} min"
        f" & echo   Total gaming:  {s['gaming_today']}"
        f" & echo   Total browser: {s['watching_today']}"
        f" & echo   Total bonus:   {s['bonus_today']}"
        f" & echo   Total other:   {s['other_today']}"
        f" & echo."
    )
    subprocess.Popen(
        ["cmd", "/c", f"echo. & echo  {msg} & pause"],
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )


def _on_show_logs(icon, item):  # pylint: disable=unused-argument
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


def _on_quit(icon, item):  # pylint: disable=unused-argument
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
        pystray.MenuItem("Status", _on_status, default=True),
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

    remaining_seconds = max(0.0, state.remaining_budget_seconds)
    remaining = format_mmss(remaining_seconds)
    overtime_seconds = getattr(state, "overtime_seconds", 0.0)
    overtime_str = format_mmss(overtime_seconds)
    extra_today = int(load_extra_minutes_given_today())

    if overtime_seconds > 0:
        main_line = f"Overtime: {overtime_str}"
    else:
        main_line = f"Budget: {remaining}"

    extra_part = f"Extra: {extra_today}/{MAX_EXTRA_MINUTES_PER_DAY}"
    if state.is_tracked_activity_running:
        _icon.title = (
            "HotTurkey\n"
            f"{main_line}\n"
            f"{extra_part}\n"
            f"Activity: {state.tracked_activity_name}"
        )
    else:
        _icon.title = "HotTurkey\n" f"{main_line}\n" f"{extra_part}"
