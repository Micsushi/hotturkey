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
from hotturkey.db import (
    clear_all_sessions,
    init_db,
    query_daily_totals,
    query_sessions,
    upsert_daily_totals,
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
from hotturkey.monitor import foreground_diagnostics_report
from . import runner


def handle_status():
    """Read state.json and print the current budget and overtime info."""
    state = load_state()
    upsert_daily_totals(state)

    s = gather_status_fields(state)
    extra_cap = get_effective_max_extra_minutes_per_day()

    lw = 22
    print(f"""
            HotTurkey Status
            {('Budget remaining').ljust(lw)}: {s['remaining']} / {s['total']}
            {('Overtime debt').ljust(lw)}: {s['overtime']}
            {('Overtime level').ljust(lw)}: {s['overtime_level']}
            {('Extra today').ljust(lw)}: {s['extra_today']} / {extra_cap} min
            {('Total gaming').ljust(lw)}: {s['gaming_today']}
            {('Total entertainment').ljust(lw)}: {s['entertainment_today']}
            {('Total social').ljust(lw)}: {s['social_today']}
            {('Total bonus sites').ljust(lw)}: {s['bonus_sites_today']}
            {('Total bonus apps').ljust(lw)}: {s['bonus_apps_today']}
            {('Total other apps').ljust(lw)}: {s['other_today']}
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
    print(
        f"  Fake state: overtime={format_duration(state.overtime_seconds)}, level=L{level}"
    )
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


def _sync_db():
    init_db()
    upsert_daily_totals(load_state())


def handle_history(days, date_str, chart, plot):
    _sync_db()
    rows = query_daily_totals(days)

    if date_str:
        sessions = query_sessions(date_str)
        if not sessions:
            print(f"\n  No sessions recorded for {date_str}.\n")
        else:
            print(f"\n  Sessions for {date_str}:\n")
            print(f"  {'Time':<15} {'Activity':<30} {'Mode':<14} {'Duration':>8}")
            print(f"  {'-'*15} {'-'*30} {'-'*14} {'-'*8}")
            for s in sessions:
                from datetime import datetime as dt

                start = dt.fromtimestamp(s["start_ts"]).strftime("%H:%M")
                end = dt.fromtimestamp(s["end_ts"]).strftime("%H:%M")
                dur = format_duration(s["duration_s"])
                print(
                    f"  {start}-{end:<10} {s['activity']:<30} ({s['mode']:<12}) {dur:>8}"
                )
            print()
        if plot:
            from hotturkey.plots import show_both

            show_both(rows, pie_date=date_str)
        return

    if not rows:
        print(f"\n  No history data found for the last {days} days.\n")
        if plot:
            print("  Nothing to plot.\n")
        return

    if chart:
        _print_chart(rows)
    if plot:
        from hotturkey.plots import show_both

        show_both(rows, pie_date=None)
    elif not chart:
        _print_table(rows)


def handle_pie(days, date_str):
    from hotturkey.plots import show_pie

    _sync_db()
    rows = query_daily_totals(days)
    show_pie(rows, pie_date=date_str)


def handle_bar(days):
    from hotturkey.plots import show_bar

    _sync_db()
    rows = query_daily_totals(days)
    show_bar(rows)


def handle_clear_sessions(yes):
    """Remove all rows from the sessions table (daily_totals unchanged)."""
    if not yes:
        print()
        print("  This deletes every session record in history.db.")
        print("  Run again with --yes to confirm.")
        print()
        sys.exit(1)
    n = clear_all_sessions()
    print()
    print(f"  Deleted {n} session row(s). Daily totals were not changed.")
    print()


def _print_table(rows):
    print()
    print(
        f"  {'Date':<12} {'Gaming':>8} {'Entertainment':>13} {'Social':>8} "
        f"{'BonusSite':>10} {'BonusApp':>10} {'Other':>8}"
    )
    print(f"  {'-'*12} {'-'*8} {'-'*13} {'-'*8} {'-'*10} {'-'*10} {'-'*8}")
    for r in rows:
        print(
            f"  {r['date']:<12} "
            f"{format_duration(r['gaming_s']):>8} "
            f"{format_duration(r['entertainment_s']):>13} "
            f"{format_duration(r['social_s']):>8} "
            f"{format_duration(r['bonus_sites_s']):>10} "
            f"{format_duration(r['bonus_apps_s']):>10} "
            f"{format_duration(r['other_apps_s']):>8}"
        )
    print()


_CHART_SPEC = [
    ("gaming_s", "#", "Gaming"),
    ("entertainment_s", "=", "Entertainment"),
    ("social_s", "+", "Social"),
    ("bonus_sites_s", ".", "Bonus sites"),
    ("bonus_apps_s", ":", "Bonus apps"),
    ("other_apps_s", "-", "Other"),
]
_CHART_FILL_WIDTH = 56


def _chart_segment_widths(seconds_list, fill_budget):
    n = len(seconds_list)
    if n == 0:
        return []
    fill_budget = max(fill_budget, n)
    total = sum(seconds_list)
    if total <= 0:
        return [1] * n

    budget_left = fill_budget - n
    exact = [(s / total) * budget_left for s in seconds_list]
    extra_floor = [int(e) for e in exact]
    remainder = budget_left - sum(extra_floor)
    order = sorted(range(n), key=lambda i: exact[i] - extra_floor[i], reverse=True)
    for k in range(remainder):
        extra_floor[order[k]] += 1
    return [1 + extra_floor[i] for i in range(n)]


def _print_chart(rows):
    print()
    for r in rows:
        pairs = [(key, ch) for key, ch, _ in _CHART_SPEC if r[key] > 0]
        if not pairs:
            print(f"  {r['date']}  (no activity)")
            continue
        total = sum(r[k] for k, _ in pairs)
        n = len(pairs)
        sep_slots = max(0, n - 1)
        fill_budget = max(n, _CHART_FILL_WIDTH - sep_slots)
        seconds_list = [r[k] for k, _ in pairs]
        widths = _chart_segment_widths(seconds_list, fill_budget)
        if not widths:
            continue
        parts = []
        for (key, ch), w in zip(pairs, widths):
            parts.append(ch * w)
        bar = "|".join(parts)
        total_dur = format_duration(total)
        print(f"  {r['date']}  [{bar}] {total_dur}")

    print()
    legend = "  Legend:  "
    legend += "   ".join(f"{name} ({ch})" for _, ch, name in _CHART_SPEC)
    print(legend)
    print()


def handle_focus():
    """Print foreground PID, exe, window title, and how HotTurkey would classify."""
    state = load_state()
    report = foreground_diagnostics_report(state)
    print()
    print(report)
    print()


def main():
    """Parse command-line arguments and route to the right handler."""
    parser = argparse.ArgumentParser(
        prog="hotturkey", description="HotTurkey screen time enforcer"
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("status", help="Show current budget and tracking info")

    subparsers.add_parser(
        "focus",
        help="Show foreground exe and classification (focus game window first)",
    )

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

    history_parser = subparsers.add_parser(
        "history", help="Show historical activity data"
    )
    history_parser.add_argument(
        "--days", type=int, default=7, help="Number of days to show (default: 7)"
    )
    history_parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Show sessions for a specific date (YYYY-MM-DD)",
    )
    history_parser.add_argument(
        "--chart", action="store_true", help="Show a text-based bar chart"
    )
    history_parser.add_argument(
        "--plot",
        action="store_true",
        help="Open pie + bar chart side-by-side in one window (matplotlib)",
    )

    pie_parser = subparsers.add_parser(
        "pie", help="Open a pie chart of one day's activity breakdown"
    )
    pie_parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days of data to load (default: 7)",
    )
    pie_parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Date to chart (YYYY-MM-DD). Defaults to today.",
    )

    bar_parser = subparsers.add_parser(
        "bar", help="Open a stacked bar chart of daily totals"
    )
    bar_parser.add_argument(
        "--days", type=int, default=7, help="Number of days to show (default: 7)"
    )

    clear_sess = subparsers.add_parser(
        "clear-sessions",
        help="Delete all per-session rows from the database (daily totals kept)",
    )
    clear_sess.add_argument(
        "--yes",
        action="store_true",
        help="Required: confirm you want to wipe session history",
    )

    args = parser.parse_args()

    if args.command == "status":
        handle_status()
    elif args.command == "focus":
        handle_focus()
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
    elif args.command == "history":
        handle_history(args.days, args.date, args.chart, args.plot)
    elif args.command == "pie":
        handle_pie(args.days, args.date)
    elif args.command == "bar":
        handle_bar(args.days)
    elif args.command == "clear-sessions":
        handle_clear_sessions(args.yes)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
