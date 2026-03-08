# cli.py -- Command-line interface for checking status and adding/removing time.
# Run from a separate terminal while run.py is running:
#   python -m hotturkey.cli status
#   python -m hotturkey.cli extra 30       (add 30 min)
#   python -m hotturkey.cli extra -10      (remove 10 min, won't go below 0)

import argparse
import sys

from hotturkey.config import MAX_PLAY_BUDGET, MAX_EXTRA_MINUTES_PER_DAY
from hotturkey.state import (
    load_state,
    load_extra_minutes_pending,
    load_extra_minutes_given_today,
    save_extra_minutes_pending,
    save_set_minutes,
    reset_state_to_default,
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
    overtime = _format_time(getattr(state, "overtime_seconds", 0.0))
    total = _format_time(MAX_PLAY_BUDGET)
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
    print(f"  Budget will be ~{_format_time(effective_seconds)} (next poll if app is running).")
    if future_overtime > 0:
        print(f"  Overtime debt will be ~{_format_time(future_overtime)}.")
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
    state = load_state()

    # Clear any pending extra-time deltas so 'set' is an absolute override.
    save_extra_minutes_pending(0.0)

    save_set_minutes(minutes)

    print()
    if minutes > 0:
        print(f"  Budget will be set to: {_format_time(minutes * 60)} remaining.")
        print("  Overtime will be cleared to 0.")
    elif minutes < 0:
        debt_minutes = abs(minutes)
        print("  Budget will be set to: 0:00.")
        print(f"  Overtime debt will be set to: {_format_time(debt_minutes * 60)}.")
    else:
        print("  Budget and overtime will be reset to 0:00.")
    print("  (Takes effect on next poll if app is running.)")
    print()


def handle_reset():
    """Reset all state to default: full budget, zero overtime, extra today cleared."""
    reset_state_to_default()
    total = _format_time(MAX_PLAY_BUDGET)
    print()
    print("  State reset to default.")
    print(f"  Budget: {total} (full). Overtime: 0:00. Extra today: 0/{MAX_EXTRA_MINUTES_PER_DAY}.")
    print("  Pending extra and set commands cleared.")
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

    subparsers.add_parser("reset", help="Reset all state to default (full budget, zero overtime, extra today cleared)")

    args = parser.parse_args()

    if args.command == "status":
        handle_status()
    elif args.command == "extra":
        handle_extra(args.minutes)
    elif args.command == "set":
        handle_set(args.minutes)
    elif args.command == "reset":
        handle_reset()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
