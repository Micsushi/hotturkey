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

from hotturkey.config import (
    POLL_INTERVAL,
    MAX_PLAY_BUDGET,
    STATE_DIR,
)
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

# Per-process shutdown event: each instance creates "HotTurkeyShutdown_<pid>"
# and writes its pid to STATE_DIR/run.pid so a new run can signal the correct
# process. This avoids the new instance inheriting a signaled event.
_shutdown_event = None
_PID_FILE = os.path.join(STATE_DIR, "run.pid")


def _format_mmss(seconds: float) -> str:
    """Format a number of seconds as MM:SS (e.g. 2149 -> '35:49')."""
    total = max(0, int(seconds))
    minutes = total // 60
    secs = total % 60
    return f"{minutes}:{secs:02d}"


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

    remaining_str = _format_mmss(state.remaining_budget_seconds)
    max_str = _format_mmss(MAX_PLAY_BUDGET)
    # Show both remaining budget and any stored overtime debt on startup.
    overtime_seconds = getattr(state, "overtime_seconds", 0.0)
    overtime_str = _format_mmss(overtime_seconds)
    if overtime_seconds > 0:
        log.info(f"[START] Budget: {remaining_str} / {max_str}, overtime debt: {overtime_str}")
    else:
        log.info(f"[START] Budget: {remaining_str} / {max_str}")
    log.debug(f"[DEBUG] Poll interval: {POLL_INTERVAL}s")

    while _running:
        loop_start = time.time()

        t0 = time.time()
        update_budget(state)
        t1 = time.time()

        t2 = time.time()
        check_and_trigger_popups(state)
        t3 = time.time()

        t4 = time.time()
        update_tray_icon(state)
        t5 = time.time()

        t6 = time.time()
        save_state(state)
        t7 = time.time()

        body_ms = (time.time() - loop_start) * 1000.0
        log.debug(
            "[PERF] Loop: "
            f"update_budget={ (t1 - t0) * 1000.0:.1f}ms, "
            f"popups={ (t3 - t2) * 1000.0:.1f}ms, "
            f"tray={ (t5 - t4) * 1000.0:.1f}ms, "
            f"save_state={ (t7 - t6) * 1000.0:.1f}ms, "
            f"total_body={ body_ms:.1f}ms"
        )

        time.sleep(POLL_INTERVAL)

    save_state(state)
    log.info("[STOP] Monitor stopped, state saved.")


def main():
    global _running, _single_instance_mutex, _shutdown_event

    # First, try to acquire the single-instance mutex.
    _single_instance_mutex = win32event.CreateMutex(None, False, _MUTEX_NAME)
    last_error = win32api.GetLastError()

    if last_error == winerror.ERROR_ALREADY_EXISTS:
        # Another instance is running. Signal it to exit, then wait until it has
        # released the mutex so we don't start a second tray/monitor.
        log.info("[START] HotTurkey is already running, requesting restart...")
        try:
            with open(_PID_FILE, "r") as f:
                old_pid = int(f.read().strip())
            existing = win32event.OpenEvent(
                win32event.EVENT_MODIFY_STATE, False, f"HotTurkeyShutdown_{old_pid}"
            )
            win32event.SetEvent(existing)
        except Exception:
            log.info("[START] Could not signal existing instance; exiting to avoid two instances.")
            return

        # Wait until the old process has exited (it will close its mutex handle).
        # We release our handle and re-create the mutex; once we get it without
        # ALREADY_EXISTS, we are the only instance.
        for _ in range(15):
            time.sleep(1)
            try:
                win32api.CloseHandle(_single_instance_mutex)
            except Exception:
                pass
            _single_instance_mutex = win32event.CreateMutex(None, False, _MUTEX_NAME)
            last_error = win32api.GetLastError()
            if last_error != winerror.ERROR_ALREADY_EXISTS:
                break
        if last_error == winerror.ERROR_ALREADY_EXISTS:
            log.info("[START] Existing instance did not exit in time; exiting.")
            return

    log.info("============================================================")
    log.info("[START] HotTurkey starting...")

    # Record our PID and create our own shutdown event so a future restart
    # can signal this process only (avoids new instance seeing old event).
    pid = os.getpid()
    os.makedirs(os.path.dirname(_PID_FILE), exist_ok=True)
    with open(_PID_FILE, "w") as f:
        f.write(str(pid))
    _shutdown_event = win32event.CreateEvent(
        None, False, False, f"HotTurkeyShutdown_{pid}"
    )

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

    # Main thread waits for either Ctrl+C or a shutdown event from a new run.
    try:
        while _running:
            # Wait up to 500ms for the shutdown event; timeout keeps Ctrl+C responsive.
            if _shutdown_event is not None:
                rc = win32event.WaitForSingleObject(_shutdown_event, 500)
                if rc == win32event.WAIT_OBJECT_0:
                    log.info("[STOP] Restart requested, shutting down...")
                    _running = False
                    break
            else:
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
