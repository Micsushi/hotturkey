# popup.py -- Spawns fullscreen red terminal popups when you're in overtime.

import os
import random
import subprocess
import tempfile
from pathlib import Path

from hotturkey.config import (
    MAX_PLAY_BUDGET,
    OVERTIME_INTERVAL_DECAY_FACTOR,
    OVERTIME_MIN_INTERVAL_SECONDS,
    SOCIAL_CONSUME_RATIO,
)
from hotturkey.logger import log
from hotturkey.utils import format_duration
from hotturkey.state import overtime_level_from_debt


def _ascii_art_dir():
    return Path(__file__).resolve().parent / "ascii_art"


def _popup_message_pool_dir():
    # Keep popup text messages separate from ASCII art.
    return Path(__file__).resolve().parent / "popup_messages"


def _pick_random_popup_extra_message():
    """Return one random line from popup_messages/popup_messages.txt."""
    pool_path = _popup_message_pool_dir() / "popup_messages.txt"
    if not pool_path.is_file():
        return None

    try:
        lines = pool_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        log.warning("[POPUP] could not read popup message pool=%s", pool_path)
        return None

    messages = [ln.strip() for ln in lines if ln.strip()]
    if not messages:
        return None
    return random.choice(messages)


def _overtime_base_interval_seconds() -> float:
    # Mirrors `overtime_level_from_debt()` logic (base interval for L2+ spacing).
    return max(
        float(OVERTIME_MIN_INTERVAL_SECONDS),
        0.5 * float(MAX_PLAY_BUDGET),
    )


def _overtime_threshold_for_level(target_level: int):
    """Return the overtime seconds needed to reach `target_level`.

    Must mirror `overtime_level_from_debt()` in state.py exactly.
    Returns None if the level is unreachable (intervals shrink below 1s).
    """
    if target_level <= 0:
        return 0.0
    if target_level == 1:
        return 0.0

    base_interval = _overtime_base_interval_seconds()

    # L2 fires when overtime strictly exceeds base_interval (> not >=).
    # L3+ fire when remaining >= interval (>=).
    # We return the boundary value; the caller treats it as "just past this".
    cumulative = base_interval
    if target_level == 2:
        return cumulative

    interval = base_interval * float(OVERTIME_INTERVAL_DECAY_FACTOR)
    for _lvl in range(3, target_level + 1):
        if interval < 1.0:
            return None
        cumulative += interval
        interval *= float(OVERTIME_INTERVAL_DECAY_FACTOR)

    return cumulative


def _pick_random_ascii_art():
    d = _ascii_art_dir()
    if not d.is_dir():
        return None
    files = [p for p in d.iterdir() if p.suffix.lower() == ".txt" and p.is_file()]
    if not files:
        return None
    path = random.choice(files)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        log.warning("[POPUP] could not read ascii art file=%s", path)
        return None
    text = text.strip()
    return text or None


def _show_fullscreen_popup_simple(message):
    # Simple console layout: red background, white text, big-ish window, message, then pause.
    # Keep this "simple" fallback safe for cmd parsing: first line only.
    first = (message or "").splitlines()[0] if message else ""
    safe = (
        first[:300]
        .replace("&", "and")
        .replace("|", " ")
        .replace("^", "")
        .replace(">", " ")
        .replace("<", " ")
    )
    cmd = f"color 4F & mode con cols=120 lines=30 & echo. & echo {safe} & echo. & pause"
    subprocess.Popen(
        ["cmd", "/c", "start", "", "/max", "cmd", "/c", cmd],
    )


def _has_windows_terminal() -> bool:
    """Return True if Windows Terminal (wt.exe) is on PATH."""
    import shutil
    return shutil.which("wt") is not None


def _show_fullscreen_popup_with_body(body):
    """Red console; prints multi-line body from a temp file."""
    txt_path = None
    bat_path = None
    ps1_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".txt",
            delete=False,
            encoding="utf-8",
            newline="\n",
        ) as tf:
            tf.write(body)
            txt_path = tf.name

        txt_win = str(Path(txt_path).resolve())

        if _has_windows_terminal():
            # Windows Terminal renders all Unicode (Braille, emoji) correctly.
            # Use a PowerShell script so we get red background + white text.
            ps_lines = [
                "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8",
                "$Host.UI.RawUI.BackgroundColor = 'DarkRed'",
                "$Host.UI.RawUI.ForegroundColor = 'White'",
                "Clear-Host",
                f'Get-Content -Path "{txt_win}" -Encoding UTF8',
                "Write-Host ''",
                "Write-Host 'Press any key to close...'",
                "$null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')",
            ]
            ps_body = "\r\n".join(ps_lines) + "\r\n"

            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".ps1",
                delete=False,
                encoding="utf-8",
                newline="",
            ) as pf:
                pf.write(ps_body)
                ps1_path = pf.name

            ps1_win = str(Path(ps1_path).resolve())
            subprocess.Popen([
                "wt", "--maximized",
                "powershell", "-ExecutionPolicy", "Bypass", "-File", ps1_win,
            ])
        else:
            # Fallback: classic cmd.exe (Braille/emoji may show as ?? depending on font).
            bat_lines = [
                "@echo off",
                "chcp 65001 >nul",
                "color 4F",
                "mode con cols=120 lines=50",
                f'type "{txt_win}"',
                "echo.",
                "pause",
            ]
            bat_body = "\r\n".join(bat_lines) + "\r\n"

            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".bat",
                delete=False,
                encoding="utf-8",
                newline="",
            ) as bf:
                bf.write(bat_body)
                bat_path = bf.name

            subprocess.Popen(
                ["cmd", "/c", "start", "", "/max", "cmd", "/c", bat_path],
            )
    except OSError:
        for p in (txt_path, bat_path, ps1_path):
            if p:
                try:
                    os.unlink(p)
                except OSError:
                    pass
        raise


def _fit_body_to_console(body, *, max_cols: int, max_lines: int) -> str:
    """Truncate wide/tall ASCII so it fits the fixed terminal size."""
    # `cmd`'s `mode con cols=... lines=...` is best-effort; still, keep output bounded.
    lines = body.splitlines()
    max_lines = max(1, max_lines)
    max_cols = max(1, max_cols)

    if len(lines) > max_lines:
        lines = lines[: max_lines - 1] + ["..."]

    fitted = []
    for line in lines:
        fitted.append(line[:max_cols])

    return "\n".join(fitted).strip()


def _build_popup_top_text(state, level: int) -> str:
    """Header text printed above the ASCII art."""
    extra_message = _pick_random_popup_extra_message() or "Overtime detected."

    overtime_seconds = float(getattr(state, "overtime_seconds", 0.0))
    remaining_budget_seconds = float(getattr(state, "remaining_budget_seconds", 0.0))
    mode = getattr(state, "current_session_mode", "") or ""

    total_to_recover = max(0.0, overtime_seconds) + max(0.0, float(MAX_PLAY_BUDGET) - remaining_budget_seconds)

    next_level = level + 1
    threshold_next = _overtime_threshold_for_level(next_level)
    growth_per_sec = float(SOCIAL_CONSUME_RATIO) if mode == "social" else 1.0
    if threshold_next is None:
        next_line = "Next level: max reached"
    else:
        needed = max(0.0, float(threshold_next) - overtime_seconds)
        eta = format_duration(needed / growth_per_sec) if growth_per_sec > 0 else "?"
        next_line = f"Next level: L{next_level} in ~{eta}"

    lines = [
        extra_message,
        "",
        f"Overtime: {format_duration(overtime_seconds)}  |  Level: L{level}",
        next_line,
        f"Full recovery: {format_duration(total_to_recover)}",
    ]
    return "\n".join(lines).strip()


_CONSOLE_COLS = 120
_MAX_ART_LINES = 35


def show_fullscreen_popup(message):
    art = _pick_random_ascii_art()
    used_art = False
    body = message or ""
    if art:
        try:
            art_lines = art.splitlines()
            if len(art_lines) > _MAX_ART_LINES:
                art_lines = art_lines[:_MAX_ART_LINES]
            trimmed_art = "\n".join(art_lines)

            body = f"{message}\n\n{trimmed_art}"
            fitted_body = _fit_body_to_console(body, max_cols=_CONSOLE_COLS - 2, max_lines=45)
            _show_fullscreen_popup_with_body(fitted_body)
            used_art = True
        except OSError as exc:
            log.warning("[POPUP] ascii popup failed, using simple fallback err=%s", exc)
            body = message or ""
    if not used_art:
        fitted_body = _fit_body_to_console(body, max_cols=_CONSOLE_COLS - 2, max_lines=45)
        try:
            _show_fullscreen_popup_with_body(fitted_body)
        except OSError:
            _show_fullscreen_popup_simple(body)
    log.info("[POPUP] event=fullscreen ascii=%s message=%s", used_art, message)


def check_and_trigger_popups(state):

    is_active = state.is_tracked_activity_running

    # Popups based on how much *overtime* we've accumulated, only start counting once budget is at/below 0.
    if state.remaining_budget_seconds > 0:
        state.overtime_escalation_level = 0
        return

    overtime = getattr(state, "overtime_seconds", 0.0)
    if overtime <= 0:
        state.overtime_escalation_level = 0
        return

    level = overtime_level_from_debt(overtime)
    prev_level = state.overtime_escalation_level
    state.overtime_escalation_level = level

    if not is_active:
        return

    # When we cross into a new level during an active session, fire a popup.
    if level > prev_level:
        top_text = _build_popup_top_text(state, level)
        # Keep the existing "close to what triggered this" flavor by appending session time.
        used = format_duration(float(getattr(state, "seconds_used_this_session", 0.0)))
        top_text = f"{top_text}\n\nSession: {used} on this activity"
        show_fullscreen_popup(top_text)
