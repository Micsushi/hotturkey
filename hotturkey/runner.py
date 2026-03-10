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
from hotturkey.state import (
    load_state,
    save_state,
    load_extra_minutes_given_today,
    check_and_clear_reload_flag,
)
from hotturkey.monitor import update_budget
from hotturkey.popup import check_and_trigger_popups
from hotturkey.tray import create_tray_icon, update_tray_icon
from hotturkey.logger import log, log_event


_running = True
_shutdown_reason = None

_single_instance_mutex = None
_MUTEX_NAME = "HotTurkeySingleton"

_shutdown_event = None
_PID_FILE = os.path.join(STATE_DIR, "run.pid")


def _format_mmss(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes = total // 60
    secs = total % 60
    return f"{minutes}:{secs:02d}"


def monitor_loop():
    global _running, _shutdown_reason

    state = load_state()

    state.is_tracked_activity_running = False
    state.tracked_activity_name = ""
    state.last_poll_timestamp = time.time()

    remaining_str = _format_mmss(state.remaining_budget_seconds)
    max_str = _format_mmss(MAX_PLAY_BUDGET)
    overtime_seconds = getattr(state, "overtime_seconds", 0.0)
    overtime_str = _format_mmss(overtime_seconds)
    extra_today = load_extra_minutes_given_today()
    log_event(
        "START",
        budget=f"{remaining_str}/{max_str}",
        overtime=overtime_str,
        extra_today=f"{int(extra_today)}/{MAX_EXTRA_MINUTES_PER_DAY}",
    )
    log.debug("[DEBUG] poll_interval_s=%s", POLL_INTERVAL)

    while _running:
        loop_start = time.time()

        if check_and_clear_reload_flag():
            state = load_state()
            state.is_tracked_activity_running = False
            state.tracked_activity_name = ""
            state.last_poll_timestamp = time.time()
            log.info("[COMMAND] reset: state to default.")
            log_event(
                "START",
                event="reloaded",
                budget=f"{_format_mmss(state.remaining_budget_seconds)}/{_format_mmss(MAX_PLAY_BUDGET)}",
            )

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
            "[PERF] update_budget_ms=%.1f popups_ms=%.1f tray_ms=%.1f "
            "save_state_ms=%.1f total_body_ms=%.1f",
            (t1 - t0) * 1000.0,
            (t3 - t2) * 1000.0,
            (t5 - t4) * 1000.0,
            (t7 - t6) * 1000.0,
            body_ms,
        )

        time.sleep(POLL_INTERVAL)

    save_state(state)
    if _shutdown_reason != "restart":
        log_event("STOP", event="monitor_stopped", state="saved")


def main():
    global _running, _single_instance_mutex, _shutdown_event, _shutdown_reason

    _single_instance_mutex = win32event.CreateMutex(None, False, _MUTEX_NAME)
    last_error = win32api.GetLastError()

    if last_error == winerror.ERROR_ALREADY_EXISTS:
        log.info("[COMMAND] start: app already running, requesting restart.")
        try:
            with open(_PID_FILE, "r") as f:
                old_pid = int(f.read().strip())
            existing = win32event.OpenEvent(
                win32event.EVENT_MODIFY_STATE,
                False,
                f"HotTurkeyShutdown_{old_pid}",
            )
            win32event.SetEvent(existing)
        except Exception:
            log_event("START", event="could_not_signal", action="exiting")
            return

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
        None,
        False,
        False,
        f"HotTurkeyShutdown_{pid}",
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
                rc = win32event.WaitForSingleObject(_shutdown_event, 500)
                if rc == win32event.WAIT_OBJECT_0:
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
    if os.environ.get("HOTTURKEY_DETACHED") != "1":
        env = os.environ.copy()
        env["HOTTURKEY_DETACHED"] = "1"
        package_dir = os.path.dirname(os.path.abspath(__file__))
        root_dir = os.path.dirname(package_dir)
        run_path = os.path.join(root_dir, "run.py")
        subprocess.Popen(
            [sys.executable, run_path],
            cwd=root_dir,
            env=env,
            creationflags=(
                subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            ),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(
            "HotTurkey started (or is already running) in background. "
            "You can close this terminal."
        )
        print("Right-click the tray icon for Status, Show logs, or Quit.")
        sys.exit(0)

    main()

