# cli commands for the user to use

import argparse
import os
import sys
import win32event

from hotturkey.config import (
    MAX_PLAY_BUDGET,
    get_effective_max_extra_minutes_per_day,
    STATE_DIR,
    LOG_LEVEL_FILE,
)
from hotturkey.state import (
    load_state,
    load_extra_minutes_pending,
    load_extra_minutes_given_today,
    save_extra_minutes_pending,
    save_set_minutes,
    reset_state_to_default,
    apply_extra_seconds,
    gather_status_fields,
)
from hotturkey.utils import format_duration
from . import runner


def handle_status():
    """Read state.json and print the current budget and overtime info."""
    state = load_state()
    s = gather_status_fields(state)
    extra_cap = get_effective_max_extra_minutes_per_day()

    print(f"""
            HotTurkey Status
            Budget remaining : {s['remaining']} / {s['total']}
            Overtime debt    : {s['overtime']}
            Overtime level   : {s['overtime_level']}
            Extra today      : {s['extra_today']} / {extra_cap} min
            Total gaming     : {s['gaming_today']}
            Total browser    : {s['watching_today']}
            Total social     : {s['social_today']}
            Total bonus      : {s['bonus_today']}
            Total other apps : {s['other_today']}
        """)


def handle_extra(minutes):
    """Add or remove minutes from the budget. Positive adds, negative deducts.
    If add is not running it will queue the extra when starting up.
    Positive extra is capped by the daily limit (double on Tue/Thu/Sat/Sun)."""
    if minutes == 0:
        print("  Minutes can't be 0.")
        sys.exit(1)

    if minutes > 0:
        extra_cap = get_effective_max_extra_minutes_per_day()
        given_today = load_extra_minutes_given_today()
        pending_minutes = load_extra_minutes_pending()
        remaining_cap = max(0.0, extra_cap - given_today - pending_minutes)
        if remaining_cap <= 0:
            print(
                f"  Daily extra-minutes limit reached ({extra_cap} min/day). Try again tomorrow."
            )
            sys.exit(1)
        if minutes > remaining_cap:
            minutes = remaining_cap
            print(f"  Capped to {minutes:.0f} min (daily limit {extra_cap} min).")

    state = load_state()
    pending_minutes = load_extra_minutes_pending()
    pending_minutes += minutes
    save_extra_minutes_pending(pending_minutes)

    # predict future budget/overtime
    pending_minutes_total = load_extra_minutes_pending()
    pending_secs = pending_minutes_total * 60
    budget_before = state.remaining_budget_seconds
    overtime_before = getattr(state, "overtime_seconds", 0.0)
    budget_after, overtime_after = apply_extra_seconds(
        budget_before, overtime_before, pending_secs
    )

    effective_seconds = max(0.0, budget_after)
    print()
    if minutes > 0:
        print(f"  Added {minutes} minutes.")
    else:
        print(f"  Deducted {abs(minutes)} minutes.")
    print(
        f"  Budget will be ~{format_duration(effective_seconds)} (next poll if app is running)."
    )
    if overtime_after > 0:
        print(f"  Overtime debt will be ~{format_duration(overtime_after)}.")
    print()


def handle_set(minutes):
    """Set budget/overtime explicitly
    - Positive minutes: set remaining budget to this and clear any overtime
    - Negative minutes: set budget to 0 and set overtime to this
    - Zero: set both budget and overtime to 0.
    """
    save_extra_minutes_pending(0.0)
    save_set_minutes(minutes)

    print()
    if minutes > 0:
        print(f"  Budget will be set to: {format_duration(minutes * 60)} remaining.")
        print("  Overtime will be cleared to 0.")
    elif minutes < 0:
        debt_minutes = abs(minutes)
        print("  Budget will be set to: 0:00.")
        print(f"  Overtime debt will be set to: {format_duration(debt_minutes * 60)}.")
    else:
        print("  Budget and overtime will be reset to 0:00.")
    print("  (Takes effect on next poll if app is running.)")
    print()


def handle_reset():
    """Reset all state to default: full budget, zero overtime, extra today cleared."""
    reset_state_to_default()
    total = format_duration(MAX_PLAY_BUDGET)
    print()
    print("  State reset to default.")
    extra_cap = get_effective_max_extra_minutes_per_day()
    print(f"  Budget: {total} (full). Overtime: 0:00. Extra today: 0/{extra_cap}.")
    print("  Pending extra and set commands cleared.")
    print("  (Takes effect on next poll if app is running.)")
    print()


def handle_run():
    runner.launch()


def handle_stop():
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


def handle_testpopup():
    """Fire a single test popup with random art + random message using fake overtime state."""
    import random
    from hotturkey.state import AppState
    from hotturkey.popup import show_fullscreen_popup, _build_popup_top_text

    state = AppState()
    state.remaining_budget_seconds = 0.0
    state.overtime_seconds = float(random.randint(60, 3600))
    state.seconds_used_this_session = float(random.randint(300, 7200))
    state.current_session_mode = "consume"
    state.is_tracked_activity_running = True

    level = random.randint(1, 5)
    top_text = _build_popup_top_text(state, level)
    used = format_duration(state.seconds_used_this_session)
    top_text = f"{top_text}\n\nSession: {used} on this activity"

    print()
    print("  Firing test popup...")
    print(f"  Fake state: overtime={format_duration(state.overtime_seconds)}, level=L{level}")
    print()
    show_fullscreen_popup(top_text)


def handle_morelog():
    _set_log_level("DEBUG")
    print()
    print("  Log level set to DEBUG (verbose, includes [PERF] timing).")
    print("  If HotTurkey is running, it will pick this up within one poll.")
    print()


def handle_lesslog():
    _set_log_level("INFO")
    print()
    print("  Log level set to INFO (normal, concise logs).")
    print("  If HotTurkey is running, it will pick this up within one poll.")
    print()


def main():
    """Parse command-line arguments and route to the right handler."""
    parser = argparse.ArgumentParser(
        prog="hotturkey", description="HotTurkey screen time enforcer"
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("status", help="Show current budget and tracking info")

    extra_parser = subparsers.add_parser(
        "extra", help="Add or remove play time in minutes (negative to deduct)"
    )
    extra_parser.add_argument(
        "minutes", type=float, help="Minutes to add (positive) or deduct (negative)"
    )

    set_parser = subparsers.add_parser(
        "set", help="Set budget to an exact number of minutes"
    )
    set_parser.add_argument(
        "minutes", type=float, help="Total minutes of budget to allow"
    )

    # Temporarily disable the 'reset' command. Keeping the handler defined so we can
    # re-enable this later without changing behavior elsewhere.
    # subparsers.add_parser(
    #     "reset",
    #     help="Reset all state to default (full budget, zero overtime, extra today cleared)",
    # )

    subparsers.add_parser(
        "run", help="Start HotTurkey (tray + monitor) in the background"
    )
    subparsers.add_parser("stop", help="Ask the running HotTurkey process to exit")

    subparsers.add_parser(
        "testpopup", help="Fire a single test popup with random art and message"
    )

    subparsers.add_parser(
        "morelog", help="Set log level to DEBUG and restart HotTurkey"
    )
    subparsers.add_parser("lesslog", help="Set log level to INFO and restart HotTurkey")

    args = parser.parse_args()

    if args.command == "status":
        handle_status()
    elif args.command == "extra":
        handle_extra(args.minutes)
    elif args.command == "set":
        handle_set(args.minutes)
    # 'reset' command is currently disabled.
    # elif args.command == "reset":
    #     handle_reset()
    elif args.command == "run":
        handle_run()
    elif args.command == "stop":
        handle_stop()
    elif args.command == "testpopup":
        handle_testpopup()
    elif args.command == "morelog":
        handle_morelog()
    elif args.command == "lesslog":
        handle_lesslog()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
