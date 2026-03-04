# cli.py -- Command-line interface for checking status and adding/removing time.
# Run from a separate terminal while run.py is running:
#   python -m hotturkey.cli status
#   python -m hotturkey.cli extra 30       (add 30 min)
#   python -m hotturkey.cli extra -10      (remove 10 min, won't go below 0)

import argparse
import sys

from hotturkey.config import MAX_PLAY_BUDGET_SECONDS
from hotturkey.state import (
    load_state,
    load_extra_minutes_pending,
    save_extra_minutes_pending,
)


def _format_time(seconds):
    """Turn seconds into mm:ss string."""
    minutes = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{minutes}:{secs:02d}"


def handle_status():
    """Read state.json and print the current budget, activity, and session info."""
    state = load_state()
    # Effective budget includes any pending extra minutes that haven't been picked up yet
    pending_minutes = load_extra_minutes_pending()
    effective_seconds = max(0.0, state.remaining_budget_seconds + (pending_minutes * 60))
    remaining = _format_time(effective_seconds)
    total = _format_time(MAX_PLAY_BUDGET_SECONDS)
    activity = state.tracked_activity_name if state.is_tracked_activity_running else "None"
    session = _format_time(state.seconds_used_this_session) if state.is_tracked_activity_running else "N/A"

    print()
    print("  HotTurkey Status")
    print(f"    Budget remaining : {remaining} / {total}")
    print(f"    Active tracking  : {activity}")
    print(f"    Session time     : {session}")
    print(f"    Overtime level   : {state.overtime_escalation_level}")
    print()


def handle_extra(minutes):
    """Add or remove minutes from the budget. Positive adds, negative deducts.
    Works whether the app is running or not. Budget never goes below 0 when deducting."""
    if minutes == 0:
        print("  Minutes can't be 0.")
        sys.exit(1)

    state = load_state()
    pending_minutes = load_extra_minutes_pending()
    pending_minutes += minutes
    save_extra_minutes_pending(pending_minutes)

    # Show what the budget will effectively be once the app (if running) picks up the change
    effective_seconds = max(0.0, state.remaining_budget_seconds + (pending_minutes * 60))
    print()
    if minutes > 0:
        print(f"  Added {minutes} minutes.")
    else:
        print(f"  Deducted {abs(minutes)} minutes.")
    print(f"  Budget will be ~{_format_time(effective_seconds)} (next poll if app is running).")
    print()


def handle_set(minutes):
    """Set the budget to an exact number of minutes (target value).
    Implemented as a delta added to extra_minutes_pending_from_cli so it stays
    in sync with the running app."""
    if minutes < 0:
        print("  Minutes must be zero or positive.")
        sys.exit(1)

    state = load_state()
    pending_minutes = load_extra_minutes_pending()
    # Current effective budget (what the app will use once pending extras are applied)
    current_effective_seconds = max(
        0.0, state.remaining_budget_seconds + (pending_minutes * 60)
    )
    desired_seconds = minutes * 60
    delta_seconds = desired_seconds - current_effective_seconds
    delta_minutes = delta_seconds / 60.0

    pending_minutes += delta_minutes
    save_extra_minutes_pending(pending_minutes)

    # Recompute effective budget after applying the new pending value
    pending_minutes = load_extra_minutes_pending()
    new_effective_seconds = max(
        0.0, state.remaining_budget_seconds + (pending_minutes * 60)
    )
    print()
    print(f"  Budget set to: {_format_time(new_effective_seconds)}")
    print("  (Takes effect on next poll if app is running.)")
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

    args = parser.parse_args()

    if args.command == "status":
        handle_status()
    elif args.command == "extra":
        handle_extra(args.minutes)
    elif args.command == "set":
        handle_set(args.minutes)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
