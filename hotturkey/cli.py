# cli commands for the user to use

import argparse
import os
import sys

import win32event

from hotturkey.config import MAX_PLAY_BUDGET, MAX_EXTRA_MINUTES_PER_DAY, STATE_DIR, LOG_LEVEL_FILE
from hotturkey.state import (
    load_state,
    load_extra_minutes_pending,
    load_extra_minutes_given_today,
    save_extra_minutes_pending,
    save_set_minutes,
    reset_state_to_default,
)
from hotturkey.utils import format_mmss
from . import runner


def handle_status():
    """Read state.json and print the current budget, activity, and session info."""
    state = load_state()
    # Effective budget includes any pending extra minutes that haven't been picked up yet
    pending_minutes = load_extra_minutes_pending()
    effective_seconds = max(0.0, state.remaining_budget_seconds + (pending_minutes * 60))
    remaining = format_mmss(effective_seconds)
    overtime = format_mmss(getattr(state, "overtime_seconds", 0.0))
    total = format_mmss(MAX_PLAY_BUDGET)
    activity = state.tracked_activity_name if state.is_tracked_activity_running else "None"
    session = _format_time(state.seconds_used_this_session) if state.is_tracked_activity_running else "N/A"

    print()
    print("  HotTurkey Status")
    print(f"    Budget remaining : {remaining} / {total}")
    print(f"    Overtime debt    : {overtime}")
    print(f"    Active tracking  : {activity}")
    print(f"    Session time     : {session}")
    print(f"    Overtime level   : {state.overtime_escalation_level}")
    print()


def handle_extra(minutes):
    """Add or remove minutes from the budget. Positive adds, negative deducts.
    Works whether the app is running or not. Budget never goes below 0 when deducting.
    Positive extra is capped by MAX_EXTRA_MINUTES_PER_DAY (resets each day)."""
    if minutes == 0:
        print("  Minutes can't be 0.")
        sys.exit(1)

    if minutes > 0:
        given_today = load_extra_minutes_given_today()
        pending_minutes = load_extra_minutes_pending()
        remaining_cap = max(0.0, MAX_EXTRA_MINUTES_PER_DAY - given_today - pending_minutes)
        if remaining_cap <= 0:
            print(f"  Daily extra-minutes limit reached ({MAX_EXTRA_MINUTES_PER_DAY} min/day). Try again tomorrow.")
            sys.exit(1)
        if minutes > remaining_cap:
            minutes = remaining_cap
            print(f"  Capped to {minutes:.0f} min (daily limit {MAX_EXTRA_MINUTES_PER_DAY} min).")

    state = load_state()
    pending_minutes = load_extra_minutes_pending()
    pending_minutes += minutes
    save_extra_minutes_pending(pending_minutes)

    # Predict what the budget and overtime will be once the app (if running)
    # picks up all pending extra minutes, using the same rules as the monitor:
    #   - Positive extra clears overtime first, then adds to budget
    #   - Negative extra deducts from budget first, then becomes overtime debt
    pending_minutes = load_extra_minutes_pending()
    extra_seconds = pending_minutes * 60
    before_budget = state.remaining_budget_seconds
    before_overtime = getattr(state, "overtime_seconds", 0.0)

    future_budget = before_budget
    future_overtime = before_overtime

    if extra_seconds > 0:
        # Clear overtime, then add remainder to budget.
        debt_cleared = min(before_overtime, extra_seconds)
        future_overtime = before_overtime - debt_cleared
        extra_seconds -= debt_cleared
        if extra_seconds > 0:
            future_budget = max(0.0, before_budget + extra_seconds)
    elif extra_seconds < 0:
        # Deduct from budget, then any remainder becomes overtime.
        delta = extra_seconds  # negative
        new_budget = before_budget + delta
        if new_budget >= 0:
            future_budget = new_budget
        else:
            future_budget = 0.0
            overdraw = -new_budget
            future_overtime = before_overtime + overdraw

    effective_seconds = max(0.0, future_budget)
    print()
    if minutes > 0:
        print(f"  Added {minutes} minutes.")
    else:
        print(f"  Deducted {abs(minutes)} minutes.")
    print(f"  Budget will be ~{format_mmss(effective_seconds)} (next poll if app is running).")
    if future_overtime > 0:
        print(f"  Overtime debt will be ~{format_mmss(future_overtime)}.")
    print()


def handle_set(minutes):
    """Set budget/overtime explicitly.

    Semantics:
      - Positive minutes: set remaining budget to this many minutes and clear
        any overtime debt.
      - Negative minutes: set budget to 0 and set overtime debt to abs(minutes)
        minutes.
      - Zero: set both budget and overtime to 0.

    Implemented via a small sidecar file so it works whether the app is running
    or not; the monitor picks it up on the next poll.
    """
    # Clear any pending extra-time deltas so 'set' is an absolute override.
    save_extra_minutes_pending(0.0)

    save_set_minutes(minutes)

    print()
    if minutes > 0:
        print(f"  Budget will be set to: {format_mmss(minutes * 60)} remaining.")
        print("  Overtime will be cleared to 0.")
    elif minutes < 0:
        debt_minutes = abs(minutes)
        print("  Budget will be set to: 0:00.")
        print(f"  Overtime debt will be set to: {format_mmss(debt_minutes * 60)}.")
    else:
        print("  Budget and overtime will be reset to 0:00.")
    print("  (Takes effect on next poll if app is running.)")
    print()


def handle_reset():
    """Reset all state to default: full budget, zero overtime, extra today cleared."""
    reset_state_to_default()
    total = format_mmss(MAX_PLAY_BUDGET)
    print()
    print("  State reset to default.")
    print(f"  Budget: {total} (full). Overtime: 0:00. Extra today: 0/{MAX_EXTRA_MINUTES_PER_DAY}.")
    print("  Pending extra and set commands cleared.")
    print("  (Takes effect on next poll if app is running.)")
    print()


def handle_run():
    """Start the HotTurkey background process (same as `python run.py`)."""
    runner.launch()


def handle_stop():
    """Ask the running HotTurkey background process to exit."""
    pid_file = os.path.join(STATE_DIR, "run.pid")

    try:
        with open(pid_file, "r") as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        print()
        print("  No running HotTurkey instance found (PID file missing or invalid).")
        print()
        sys.exit(1)

    try:
        shutdown_event = win32event.OpenEvent(
            win32event.EVENT_MODIFY_STATE,
            False,
            f"HotTurkeyShutdown_{pid}",
        )
        win32event.SetEvent(shutdown_event)
    except Exception:
        print()
        print("  Could not signal the running HotTurkey process to stop.")
        print("  It may not be running, or the shutdown event could not be opened.")
        print()
        sys.exit(1)

    print()
    print("  Shutdown signal sent to HotTurkey.")
    print()


def _set_log_level(level_name: str):
    """Write the requested log level to LOG_LEVEL_FILE (e.g. DEBUG or INFO)."""
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(LOG_LEVEL_FILE, "w") as f:
        f.write(level_name.upper())


def handle_morelog():
    """Increase logging verbosity to DEBUG for the running app and future runs."""
    _set_log_level("DEBUG")
    print()
    print("  Log level set to DEBUG (verbose, includes [PERF] timing).")
    print("  If HotTurkey is running, it will pick this up within one poll.")
    print()


def handle_lesslog():
    """Reduce logging verbosity to INFO for the running app and future runs."""
    _set_log_level("INFO")
    print()
    print("  Log level set to INFO (normal, concise logs).")
    print("  If HotTurkey is running, it will pick this up within one poll.")
    print()


def main():
    """Parse command-line arguments and route to the right handler."""
    parser = argparse.ArgumentParser(prog="hotturkey", description="HotTurkey screen time enforcer")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("status", help="Show current budget and tracking info")

    extra_parser = subparsers.add_parser("extra", help="Add or remove play time in minutes (negative to deduct)")
    extra_parser.add_argument("minutes", type=float, help="Minutes to add (positive) or deduct (negative)")

    set_parser = subparsers.add_parser("set", help="Set budget to an exact number of minutes")
    set_parser.add_argument("minutes", type=float, help="Total minutes of budget to allow")

    subparsers.add_parser("reset", help="Reset all state to default (full budget, zero overtime, extra today cleared)")

    subparsers.add_parser("run", help="Start HotTurkey (tray + monitor) in the background")
    subparsers.add_parser("stop", help="Ask the running HotTurkey process to exit")

    subparsers.add_parser("morelog", help="Set log level to DEBUG and restart HotTurkey")
    subparsers.add_parser("lesslog", help="Set log level to INFO and restart HotTurkey")

    args = parser.parse_args()

    if args.command == "status":
        handle_status()
    elif args.command == "extra":
        handle_extra(args.minutes)
    elif args.command == "set":
        handle_set(args.minutes)
    elif args.command == "reset":
        handle_reset()
    elif args.command == "run":
        handle_run()
    elif args.command == "stop":
        handle_stop()
    elif args.command == "morelog":
        handle_morelog()
    elif args.command == "lesslog":
        handle_lesslog()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
