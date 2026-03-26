import os
import sqlite3
from datetime import date, timedelta

from hotturkey.config import HISTORY_DB, STATE_DIR
from hotturkey.logger import log


def _connect():
    os.makedirs(STATE_DIR, exist_ok=True)
    conn = sqlite3.connect(HISTORY_DB, timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = _connect()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_totals (
                date              TEXT PRIMARY KEY,
                gaming_s          REAL DEFAULT 0,
                entertainment_s   REAL DEFAULT 0,
                social_s          REAL DEFAULT 0,
                bonus_sites_s     REAL DEFAULT 0,
                bonus_apps_s      REAL DEFAULT 0,
                other_apps_s      REAL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                date         TEXT NOT NULL,
                activity     TEXT NOT NULL,
                mode         TEXT NOT NULL,
                start_ts     REAL NOT NULL,
                end_ts       REAL NOT NULL,
                duration_s   REAL NOT NULL
            )
        """)
        conn.commit()
    finally:
        conn.close()


def upsert_daily_totals(state):
    date_str = getattr(state, "session_totals_date", None) or date.today().isoformat()
    gaming = getattr(state, "gaming_seconds_today", 0.0)
    entertainment = getattr(state, "entertainment_seconds_today", 0.0)
    social = getattr(state, "social_seconds_today", 0.0)
    bonus_sites = getattr(state, "bonus_sites_seconds_today", 0.0)
    bonus_apps = getattr(state, "bonus_apps_seconds_today", 0.0)
    other = getattr(state, "other_apps_seconds_today", 0.0)

    if gaming + entertainment + social + bonus_sites + bonus_apps + other <= 0:
        return

    try:
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT INTO daily_totals
                    (date, gaming_s, entertainment_s, social_s, bonus_sites_s, bonus_apps_s, other_apps_s)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    gaming_s        = excluded.gaming_s,
                    entertainment_s = excluded.entertainment_s,
                    social_s        = excluded.social_s,
                    bonus_sites_s   = excluded.bonus_sites_s,
                    bonus_apps_s    = excluded.bonus_apps_s,
                    other_apps_s    = excluded.other_apps_s
                """,
                (
                    date_str,
                    gaming,
                    entertainment,
                    social,
                    bonus_sites,
                    bonus_apps,
                    other,
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        log.debug("[DB] failed to upsert daily totals", exc_info=True)


def insert_session(date_str, activity, mode, start_ts, end_ts, duration_s):
    if duration_s <= 0:
        return
    try:
        conn = _connect()
        try:
            last = conn.execute(
                """
                SELECT id, activity, mode, duration_s
                FROM sessions
                WHERE date = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (date_str,),
            ).fetchone()
            if last and last[1] == activity and last[2] == mode:
                sid = last[0]
                new_dur = float(last[3]) + float(duration_s)
                conn.execute(
                    """
                    UPDATE sessions
                    SET end_ts = ?, duration_s = ?
                    WHERE id = ?
                    """,
                    (end_ts, new_dur, sid),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO sessions (date, activity, mode, start_ts, end_ts, duration_s)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (date_str, activity, mode, start_ts, end_ts, duration_s),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        log.debug("[DB] failed to insert session", exc_info=True)


def clear_all_sessions() -> int:
    init_db()
    try:
        conn = _connect()
        try:
            before = conn.total_changes
            conn.execute("DELETE FROM sessions")
            conn.commit()
            return conn.total_changes - before
        finally:
            conn.close()
    except Exception:
        log.debug("[DB] failed to clear sessions", exc_info=True)
        return 0


def query_daily_totals(days=7):
    cutoff = (date.today() - timedelta(days=days - 1)).isoformat()
    try:
        conn = _connect()
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT date, gaming_s, entertainment_s, social_s,
                       bonus_sites_s, bonus_apps_s, other_apps_s
                FROM daily_totals
                WHERE date >= ?
                ORDER BY date DESC
                """,
                (cutoff,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
    except Exception:
        log.debug("[DB] failed to query daily totals", exc_info=True)
        return []


def query_daily_total(date_str):
    try:
        conn = _connect()
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                """
                SELECT date, gaming_s, entertainment_s, social_s,
                       bonus_sites_s, bonus_apps_s, other_apps_s
                FROM daily_totals
                WHERE date = ?
                """,
                (date_str,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
    except Exception:
        log.debug("[DB] failed to query daily total", exc_info=True)
        return None


def query_sessions(date_str):
    try:
        conn = _connect()
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                """
                SELECT activity, mode, start_ts, end_ts, duration_s
                FROM sessions
                WHERE date = ?
                ORDER BY start_ts
                """,
                (date_str,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
    except Exception:
        log.debug("[DB] failed to query sessions", exc_info=True)
        return []
