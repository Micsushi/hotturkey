# App starts by launching the system tray icon on a background thread and the monitor loop on another.

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
    MAX_EXTRA_MINUTES_PER_DAY,
    STATE_DIR,
)
from hotturkey.state import load_state, save_state, load_extra_minutes_given_today, check_and_clear_reload_flag
from hotturkey.monitor import update_budget
from hotturkey.popup import check_and_trigger_popups
from hotturkey.tray import create_tray_icon, update_tray_icon
from hotturkey.logger import log, log_event, refresh_log_level_from_disk

_running = True
_shutdown_reason = None

# Mutex to make sure only one instance of the HotTurkey process can run at a time.
_single_instance_mutex = None
_MUTEX_NAME = "HotTurkeySingleton"

# Per-instance shutdown event and PID file so new runs can signal the correct process to exit
_shutdown_event = None
_PID_FILE = os.path.join(STATE_DIR, "run.pid")


def _format_mmss(seconds: float) -> str:
    """Format seconds to MM:SS"""
    total = max(0, int(seconds))
    minutes = total // 60
    secs = total % 60
    return f"{minutes}:{secs:02d}"


def _reset_session_state(state) -> None:
    """Clear per-session tracking fields and set last poll time to now"""
    state.is_tracked_activity_running = False
    state.tracked_activity_name = ""
    state.last_poll_timestamp = time.time()


def _log_start_snapshot(state, *, event: str = "start") -> None:
    """Log a START snapshot for the current state"""
    remaining_time = _format_mmss(state.remaining_budget_seconds)
    max_time = _format_mmss(MAX_PLAY_BUDGET)
    overtime_used = _format_mmss(getattr(state, "overtime_seconds", 0.0))
    extra_time_used = load_extra_minutes_given_today()

    log_event(
        "START",
        event=event,
        budget=f"{remaining_time}/{max_time}",
        overtime=overtime_used,
        extra_time_used=f"{int(extra_time_used)}/{MAX_EXTRA_MINUTES_PER_DAY}",
    )


def monitor_loop():
    """Background thread that runs every POLL_INTERVAL seconds"""
    state = load_state()

    _reset_session_state(state)
    _log_start_snapshot(state)
    log.debug("[DEBUG] poll_interval_s=%s", POLL_INTERVAL)

    while _running:
        loop_start = time.time()

        # check for log level change command
        refresh_log_level_from_disk()

        # check for reset command
        if check_and_clear_reload_flag():
            state = load_state()
            _reset_session_state(state)
            log.info("[COMMAND] reset: state to default.")
            _log_start_snapshot(state, event="reloaded")

        # detect current activity and update budget/overtime
        t0 = time.time()
        update_budget(state)
        t1 = time.time()

        # fullscreen overtime popups if needed
        t2 = time.time()
        check_and_trigger_popups(state)
        t3 = time.time()

        # refresh tray icon color and tooltip
        t4 = time.time()
        update_tray_icon(state)
        t5 = time.time()

        # update state on disk
        t6 = time.time()
        save_state(state)
        t7 = time.time()

        # log time taken per step (will need to run "hotturkey morelog" to see these)
        body_ms = (time.time() - loop_start) * 1000.0
        log.debug(
            "[PERF] update_budget_ms=%.1f popups_ms=%.1f tray_ms=%.1f save_state_ms=%.1f total_body_ms=%.1f",
            (t1 - t0) * 1000.0,
            (t3 - t2) * 1000.0,
            (t5 - t4) * 1000.0,
            (t7 - t6) * 1000.0,
            body_ms,
        )

        # Sleep until the next scheduled poll.
        time.sleep(POLL_INTERVAL)

    # Final save and STOP event once the monitor loop exits.
    save_state(state)
    if _shutdown_reason != "restart":
        log_event("STOP", event="monitor_stopped", state="saved")


def main():
    global _running, _single_instance_mutex, _shutdown_event

    # First, try to acquire the single-instance mutex.
    _single_instance_mutex = win32event.CreateMutex(None, False, _MUTEX_NAME)
    last_error = win32api.GetLastError()

    if last_error == winerror.ERROR_ALREADY_EXISTS:
        # Another instance is running. Signal it to exit, then wait until it has
        # released the mutex so we don't start a second tray/monitor.
        log.info("[COMMAND] start: app already running, requesting restart.")
        try:
            with open(_PID_FILE, "r") as f:
                old_pid = int(f.read().strip())
            existing = win32event.OpenEvent(
                win32event.EVENT_MODIFY_STATE, False, f"HotTurkeyShutdown_{old_pid}"
            )
            win32event.SetEvent(existing)
        except Exception:
            log_event("START", event="could_not_signal", action="exiting")
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
            log_event("START", event="existing_did_not_exit", action="exiting")
            return

    # We are now the only running instance; continue normal startup.
    log.info("[COMMAND] start: app started.")

    # Record our PID and create our own shutdown event so a future restart
    # can signal this process only (avoids new instance seeing old event).
    pid = os.getpid()
    os.makedirs(os.path.dirname(_PID_FILE), exist_ok=True)
    with open(_PID_FILE, "w") as f:
        f.write(str(pid))
    _shutdown_event = win32event.CreateEvent(
        None, False, False, f"HotTurkeyShutdown_{pid}"
    )

    # Tray "Quit" handler flips the main loop flag.
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
                    global _shutdown_reason
                    _shutdown_reason = "restart"
                    log.info("[COMMAND] restart: exiting.")
                    _running = False
                    break
            else:
                time.sleep(0.5)
    except KeyboardInterrupt:
        log_event("STOP", event="ctrl_c")

    # Begin shutdown: stop tray, join monitor thread, and log final STOP.
    _running = False
    icon.stop()
    monitor_thread.join(timeout=10)
    if _shutdown_reason != "restart":
        log_event("STOP", event="shutdown")


def launch():
    """Entry point for starting HotTurkey from the command line.

    Behavior matches running this file directly with `python run.py`:
    it spawns a detached background process (so it survives terminal
    close) and then exits the calling process.
    """
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


if __name__ == "__main__":
    launch()
