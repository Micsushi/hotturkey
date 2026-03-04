# cli.py -- Command-line interface for checking status and adding/removing time.
# Run from a separate terminal while run.py is running:
#   python -m hotturkey.cli status
#   python -m hotturkey.cli extra 30       (add 30 min)
#   python -m hotturkey.cli extra -10      (remove 10 min, won't go below 0)

import argparse
import sys

from hotturkey.config import MAX_PLAY_BUDGET_SECONDS
from hotturkey.state import load_state, save_state


def _format_time(seconds):
    """Turn seconds into mm:ss string."""
    minutes = int(seconds) // 60
    secs = int(seconds) % 60
    return f"{minutes}:{secs:02d}"


def handle_status():
    """Read state.json and print the current budget, activity, and session info."""
    state = load_state()
    remaining = _format_time(state.remaining_budget_seconds)
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
    Budget will never go below 0 when deducting."""
    state = load_state()

    if minutes > 0:
        state.extra_minutes_pending_from_cli += minutes
        save_state(state)
        new_budget_estimate = state.remaining_budget_seconds + (minutes * 60)
        print()
        print(f"  Added {minutes} minutes of extra time.")
        print(f"  Budget will be ~{_format_time(new_budget_estimate)} on next poll cycle.")
        print()
    elif minutes < 0:
        deduct_seconds = abs(minutes) * 60
        state.remaining_budget_seconds = max(0.0, state.remaining_budget_seconds - deduct_seconds)
        save_state(state)
        print()
        print(f"  Deducted {abs(minutes)} minutes.")
        print(f"  Budget is now: {_format_time(state.remaining_budget_seconds)}")
        print()
    else:
        print("  Minutes can't be 0.")
        sys.exit(1)


def main():
    """Parse command-line arguments and route to the right handler."""
    parser = argparse.ArgumentParser(prog="hotturkey", description="HotTurkey screen time enforcer")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("status", help="Show current budget and tracking info")

    extra_parser = subparsers.add_parser("extra", help="Add or remove play time in minutes (negative to deduct)")
    extra_parser.add_argument("minutes", type=float, help="Minutes to add (positive) or deduct (negative)")

    args = parser.parse_args()

    if args.command == "status":
        handle_status()
    elif args.command == "extra":
        handle_extra(args.minutes)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
