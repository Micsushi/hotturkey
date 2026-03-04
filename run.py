# run.py -- The main entry point. Start the app with: python run.py
# Launches the system tray icon on a background thread and the monitor loop on another.
# Ctrl+C or right-click Quit on the tray icon to stop.
# When run from a terminal, spawns a detached background process so it survives terminal close.

import os
import subprocess
import sys
import threading
import time

import win32api
import win32event
import winerror

from hotturkey.config import DETECTION_POLL_INTERVAL_SECONDS
from hotturkey.state import load_state, save_state
from hotturkey.monitor import update_budget
from hotturkey.popup import check_and_trigger_popups
from hotturkey.tray import create_tray_icon, update_tray_icon
from hotturkey.logger import log


# Flag to tell threads to stop
_running = True

# Handle to a system-wide mutex so only one instance of the background
# HotTurkey process runs at a time.
_single_instance_mutex = None
_MUTEX_NAME = "HotTurkeySingleton"


def monitor_loop():
    """Background thread that runs every 5 seconds:
    1. Detect if a game or tracked site is focused
    2. Consume or recover budget
    3. Show popups if needed
    4. Update the tray icon color and tooltip
    5. Save state to disk"""
    state = load_state()

    # Reset session flags from the previous run so we don't get ghost "Session Ended" logs.
    # Also reset the poll timestamp to now so no time passes while the app wasn't running.
    state.is_tracked_activity_running = False
    state.tracked_activity_name = ""
    state.last_poll_timestamp = time.time()

    log.info(f"[START] Budget: {state.remaining_budget_seconds:.0f}s")

    while _running:
        update_budget(state)
        check_and_trigger_popups(state)
        update_tray_icon(state)
        save_state(state)
        time.sleep(DETECTION_POLL_INTERVAL_SECONDS)

    save_state(state)
    log.info("[STOP] Monitor stopped, state saved.")


def main():
    global _running, _single_instance_mutex

    # Acquire a system-wide mutex so a second background instance exits
    # immediately instead of running two monitors/tray icons at once.
    _single_instance_mutex = win32event.CreateMutex(None, False, _MUTEX_NAME)
    last_error = win32api.GetLastError()
    if last_error == winerror.ERROR_ALREADY_EXISTS:
        log.info("[START] HotTurkey is already running, exiting this instance.")
        return

    log.info("============================================================")
    log.info("[START] HotTurkey starting...")

    def on_quit():
        global _running
        _running = False

    icon = create_tray_icon(quit_callback=on_quit)

    # Start the monitor on a background thread
    monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
    monitor_thread.start()

    # Run the tray icon on its own thread so the main thread stays free for Ctrl+C
    icon_thread = threading.Thread(target=icon.run, daemon=True)
    icon_thread.start()

    # Main thread just sleeps and waits for Ctrl+C
    try:
        while _running:
            time.sleep(0.5)
    except KeyboardInterrupt:
        log.info("[STOP] Ctrl+C received, shutting down...")

    _running = False
    icon.stop()
    monitor_thread.join(timeout=10)
    log.info("[STOP] HotTurkey shut down.")


if __name__ == "__main__":
    # If not already the detached background process, spawn one and exit.
    # This lets the app keep running after you close the terminal.
    if os.environ.get("HOTTURKEY_DETACHED") != "1":
        env = os.environ.copy()
        env["HOTTURKEY_DETACHED"] = "1"
        script_dir = os.path.dirname(os.path.abspath(__file__))
        subprocess.Popen(
            [sys.executable, os.path.abspath(__file__)],
            cwd=script_dir,
            env=env,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print("HotTurkey started (or is already running) in background. You can close this terminal.")
        print("Right-click the tray icon for Status, Show logs, or Quit.")
        sys.exit(0)

    main()
