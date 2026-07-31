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
    get_effective_max_extra_minutes_per_day,
    STATE_DIR,
)
from hotturkey.state import (
    load_state,
    save_state,
    load_extra_minutes_given_today,
    check_and_clear_reload_flag,
)
from hotturkey.monitor import update_budget
from hotturkey.popup import check_and_trigger_popups
from hotturkey.tray import create_tray_icon, update_tray_icon
from hotturkey.logger import log, log_event, refresh_log_level_from_disk
from hotturkey.utils import format_duration
from hotturkey.db import init_db

_running = True
_shutdown_reason = None

# Named mutex prevents duplicate tray and monitor processes.
_single_instance_mutex = None
_MUTEX_NAME = "HotTurkeySingleton"

# New runs use the PID file to signal the active instance.
_shutdown_event = None
_PID_FILE = os.path.join(STATE_DIR, "run.pid")


def _reset_session_state(state) -> None:
    """Clear per-session tracking fields and set last poll time to now"""
    state.is_tracked_activity_running = False
    state.tracked_activity_name = ""
    state.last_poll_timestamp = time.time()


def _log_start_snapshot(state, *, event: str = "start") -> None:
    """Log a START snapshot for the current state"""
    remaining_time = format_duration(state.remaining_budget_seconds)
    max_time = format_duration(MAX_PLAY_BUDGET)
    overtime_used = format_duration(getattr(state, "overtime_seconds", 0.0))
    extra_time_used = load_extra_minutes_given_today()

    log_event(
        "START",
        event=event,
        budget=f"{remaining_time}/{max_time}",
        overtime=overtime_used,
        extra_time_used=f"{int(extra_time_used)}/{get_effective_max_extra_minutes_per_day()}",
    )


def monitor_loop():
    """Background thread that runs every POLL_INTERVAL seconds"""
    try:
        _monitor_loop_inner()
    except Exception:
        log.critical("[CRASH] monitor thread died with exception:", exc_info=True)
        raise


def _monitor_loop_inner():
    init_db()
    state = load_state()

    _reset_session_state(state)
    _log_start_snapshot(state)
    log.debug("[DEBUG] poll_interval_s=%s", POLL_INTERVAL)

    while _running:
        loop_start = time.time()

        refresh_log_level_from_disk()

        if check_and_clear_reload_flag():
            state = load_state()
            _reset_session_state(state)
            log.info("[COMMAND] state reloaded from disk.")
            _log_start_snapshot(state, event="reloaded")

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

        loop_duration = time.time() - loop_start
        body_ms = loop_duration * 1000.0
        log.debug(
            "[PERF] update_budget_ms=%.1f popups_ms=%.1f tray_ms=%.1f save_state_ms=%.1f total_body_ms=%.1f",
            (t1 - t0) * 1000.0,
            (t3 - t2) * 1000.0,
            (t5 - t4) * 1000.0,
            (t7 - t6) * 1000.0,
            body_ms,
        )

        remaining = POLL_INTERVAL - loop_duration
        if remaining > 0:
            time.sleep(remaining)

    save_state(state)
    if _shutdown_reason != "restart":
        log_event("STOP", event="monitor_stopped", state="saved")


def main():
    global _running, _single_instance_mutex, _shutdown_event

    _single_instance_mutex = win32event.CreateMutex(None, False, _MUTEX_NAME)
    last_error = win32api.GetLastError()

    if last_error == winerror.ERROR_ALREADY_EXISTS:
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

        # Wait for the old instance to release the mutex.
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

    log.info("[COMMAND] start: app started.")

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

    monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
    monitor_thread.start()

    icon_thread = threading.Thread(target=icon.run, daemon=True)
    icon_thread.start()

    try:
        while _running:
            if _shutdown_event is not None:
                wait_result = win32event.WaitForSingleObject(_shutdown_event, 500)
                if wait_result == win32event.WAIT_OBJECT_0:
                    global _shutdown_reason
                    _shutdown_reason = "restart"
                    log.info("[COMMAND] restart: exiting.")
                    _running = False
                    break
            else:
                time.sleep(0.5)
    except KeyboardInterrupt:
        log_event("STOP", event="ctrl_c")

    _running = False
    icon.stop()
    monitor_thread.join(timeout=10)
    if _shutdown_reason != "restart":
        log_event("STOP", event="shutdown")


def launch():
    """Start HotTurkey from the command line in the background."""
    # Detach so the terminal can close.
    if os.environ.get("HOTTURKEY_DETACHED") != "1":
        env = os.environ.copy()
        env["HOTTURKEY_DETACHED"] = "1"
        script_dir = os.path.dirname(os.path.abspath(__file__))
        executable = sys.executable
        if executable.endswith("python.exe"):
            executable = executable.replace("python.exe", "pythonw.exe")
        subprocess.Popen(
            [executable, os.path.abspath(__file__)],
            cwd=script_dir,
            env=env,
            creationflags=subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(
            "HotTurkey started (or is already running) in background. You can close this terminal."
        )
        print("Right-click the tray icon for Status, Show logs, or Quit.")
        sys.exit(0)

    main()


if __name__ == "__main__":
    launch()
