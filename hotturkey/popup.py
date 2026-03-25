# popup.py -- Spawns fullscreen red terminal popups when you're in overtime.

import ctypes
import os
import random
import subprocess
import tempfile
from pathlib import Path
from typing import List

from hotturkey.config import (
    MAX_PLAY_BUDGET,
    SOCIAL_CONSUME_RATIO,
)
from hotturkey.logger import log
from hotturkey.utils import format_duration
from hotturkey.state import (
    overtime_level_from_debt,
    overtime_threshold_for_level,
)


def _ascii_art_dir():
    return Path(__file__).resolve().parent / "ascii_art"


def _popup_message_pool_dir():
    return Path(__file__).resolve().parent / "popup_messages"


def _pick_random_popup_extra_message():
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
    _prepare_windows_foreground_child()
    subprocess.Popen(
        ["cmd", "/c", "start", "", "/max", "cmd", "/c", cmd],
    )


def _has_windows_terminal() -> bool:
    import shutil
    return shutil.which("wt") is not None


def _powershell_exe() -> str:
    import shutil
    return shutil.which("pwsh") or shutil.which("powershell") or "powershell"


def _prepare_windows_foreground_child():
    if os.name != "nt":
        return
    try:
        ASFW_ANY = 0xFFFFFFFF
        ctypes.windll.user32.AllowSetForegroundWindow(ASFW_ANY)
    except (AttributeError, OSError):
        pass


def _launch_popup_powershell(ps1_win: str) -> None:
    ps_exe = _powershell_exe()
    _prepare_windows_foreground_child()
    if _has_windows_terminal():
        subprocess.Popen(
            [
                "wt",
                "-w",
                "new",
                "--maximized",
                ps_exe,
                "-NoLogo",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                ps1_win,
            ]
        )
    else:
        subprocess.Popen(
            [
                "cmd",
                "/c",
                "start",
                "",
                "/max",
                ps_exe,
                "-NoLogo",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                ps1_win,
            ]
        )


def _show_fullscreen_popup_with_body(body):
    txt_path = None
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

        ps_lines = [
            "$null = & cmd /c 'chcp 65001 >nul'",
            "[Console]::InputEncoding = [System.Text.Encoding]::UTF8",
            "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8",
            "$OutputEncoding = [System.Text.Encoding]::UTF8",
            "$Host.UI.RawUI.BackgroundColor = 'DarkRed'",
            "$Host.UI.RawUI.ForegroundColor = 'White'",
            "Clear-Host",
            "$winW = [int]$Host.UI.RawUI.WindowSize.Width",
            "$winH = [int]$Host.UI.RawUI.WindowSize.Height",
            "$fillW = [Math]::Max(1, $winW - 1)",
            "function Show-RedLine([string]$s) {",
            "  if ($s.Length -gt $fillW) { $s = $s.Substring(0, $fillW) }",
            "  else { $s = $s.PadRight($fillW) }",
            "  Write-Host $s -BackgroundColor DarkRed -ForegroundColor White",
            "}",
            f'$all = @(Get-Content -Path "{txt_win}" -Encoding UTF8)',
            "$cap = [Math]::Max(2, $winH - 2)",
            "if ($all.Count -gt $cap) { $all = $all[0..($cap - 2)] + @('...') }",
            "foreach ($line in $all) { Show-RedLine $line }",
            "Show-RedLine ''",
            "Show-RedLine 'Press any key to close...'",
            "try { $Host.UI.RawUI.WindowPosition = New-Object System.Management.Automation.Host.Coordinates(0, 0) } catch { }",
            "try { [Console]::SetWindowPosition(0, 0) } catch { }",
            "$null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')",
        ]
        ps_body = "\r\n".join(ps_lines) + "\r\n"

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".ps1",
            delete=False,
            encoding="utf-8-sig",
            newline="",
        ) as pf:
            pf.write(ps_body)
            ps1_path = pf.name

        ps1_win = str(Path(ps1_path).resolve())
        _launch_popup_powershell(ps1_win)
    except OSError:
        for p in (txt_path, ps1_path):
            if p:
                try:
                    os.unlink(p)
                except OSError:
                    pass
        raise


def _fit_body_to_console(body, *, max_cols: int, max_lines: int) -> str:
    lines = body.splitlines()
    max_lines = max(1, max_lines)
    max_cols = max(1, max_cols)

    if len(lines) > max_lines:
        lines = lines[: max_lines - 1] + ["..."]

    fitted = []
    for line in lines:
        fitted.append(line[:max_cols])

    return "\n".join(fitted).strip()


def _line_is_vertical_gap(line: str) -> bool:
    for ch in line:
        if ch in " \t":
            continue
        if ord(ch) == 0x2800:
            continue
        return False
    return True


def _collapse_vertical_blank_runs(lines: List[str], *, max_blank_run: int = 1) -> List[str]:
    out: List[str] = []
    blank_run = 0
    for line in lines:
        if _line_is_vertical_gap(line):
            blank_run += 1
            if blank_run <= max_blank_run:
                out.append(line)
        else:
            blank_run = 0
            out.append(line)
    return out


def _tighten_popup_body(text: str) -> str:
    lines = text.splitlines()
    while lines and _line_is_vertical_gap(lines[0]):
        lines.pop(0)
    while lines and _line_is_vertical_gap(lines[-1]):
        lines.pop()
    lines = _collapse_vertical_blank_runs(lines, max_blank_run=1)
    return "\n".join(lines)


def _build_popup_top_text(state, level: int) -> str:
    extra_message = _pick_random_popup_extra_message() or "Overtime detected."

    overtime_seconds = float(getattr(state, "overtime_seconds", 0.0))
    remaining_budget_seconds = float(getattr(state, "remaining_budget_seconds", 0.0))
    mode = getattr(state, "current_session_mode", "") or ""

    total_to_recover = max(0.0, overtime_seconds) + max(0.0, float(MAX_PLAY_BUDGET) - remaining_budget_seconds)

    next_level = level + 1
    threshold_next = overtime_threshold_for_level(next_level)
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

            body = _tighten_popup_body(f"{message.rstrip()}\n{trimmed_art}")
            fitted_body = _fit_body_to_console(
                body, max_cols=_CONSOLE_COLS - 2, max_lines=45
            )
            _show_fullscreen_popup_with_body(fitted_body)
            used_art = True
        except OSError as exc:
            log.warning("[POPUP] ascii popup failed, using simple fallback err=%s", exc)
            body = message or ""
    if not used_art:
        fitted_body = _fit_body_to_console(
            _tighten_popup_body(body), max_cols=_CONSOLE_COLS - 2, max_lines=45
        )
        try:
            _show_fullscreen_popup_with_body(fitted_body)
        except OSError:
            _show_fullscreen_popup_simple(body)
    log.info("[POPUP] event=fullscreen ascii=%s message=%s", used_art, message)


def check_and_trigger_popups(state):

    is_active = state.is_tracked_activity_running

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

    if level > prev_level:
        top_text = _build_popup_top_text(state, level)
        used = format_duration(float(getattr(state, "seconds_used_this_session", 0.0)))
        top_text = f"{top_text}\nSession: {used} on this activity"
        show_fullscreen_popup(top_text)
