# Enumerate visible top-level Win32 windows for CLI tooling.

from __future__ import annotations

import ctypes
from dataclasses import dataclass

import psutil
import win32gui
import win32process

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
GW_OWNER = 4


user32 = ctypes.windll.user32


def _is_tool_window(hwnd: int) -> bool:
    try:
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        return bool(style & WS_EX_TOOLWINDOW)
    except OSError:
        return False


def _exe_for_pid(pid: int) -> tuple[str, str]:
    """Return (basename.exe or unknown, exe path or '')."""
    try:
        proc = psutil.Process(pid)
        base = proc.name()
        path = ""
        try:
            path = proc.exe()
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            path = ""
        return base or "(unknown)", path
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.Error):
        return "(unknown)", ""


def title_for_pid(pid: int) -> str:
    """First visible, non-empty title among top-level windows owned by PID."""
    found = ""

    def cb(hwnd: int, _acc) -> None:
        nonlocal found
        if found:
            return
        if not win32gui.IsWindowVisible(hwnd):
            return
        if win32gui.GetWindow(hwnd, GW_OWNER):
            return
        try:
            _, wpid = win32process.GetWindowThreadProcessId(hwnd)
        except (OSError, win32gui.error):
            return
        if wpid != pid:
            return
        t = win32gui.GetWindowText(hwnd)
        if t and t.strip():
            found = t

    win32gui.EnumWindows(cb, None)
    return found


@dataclass(frozen=True)
class TopLevelWindowRow:
    hwnd: int
    pid: int
    exe_basename: str
    exe_path: str
    title: str


def list_visible_top_level_windows(
    include_blank_titles: bool = False,
) -> list[TopLevelWindowRow]:
    rows: list[TopLevelWindowRow] = []

    def cb(hwnd: int, _acc) -> None:
        if not win32gui.IsWindowVisible(hwnd):
            return
        if win32gui.GetWindow(hwnd, GW_OWNER):
            return
        if _is_tool_window(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if not include_blank_titles and not (title or "").strip():
            return
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
        except (OSError, win32gui.error):
            return
        basename, path = _exe_for_pid(pid)
        rows.append(
            TopLevelWindowRow(
                hwnd=int(hwnd),
                pid=int(pid),
                exe_basename=basename,
                exe_path=path,
                title=title or "",
            )
        )

    win32gui.EnumWindows(cb, None)
    rows.sort(key=lambda r: (r.exe_basename.lower(), r.title.lower()))
    return rows
