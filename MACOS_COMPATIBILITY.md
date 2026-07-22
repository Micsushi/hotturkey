# macOS Compatibility Notes

Audit date: 2026-07-03

## Status

Not macOS-compatible as an app today. The project is Windows-specific and imports Win32 modules at startup.

This was audited from Ubuntu, so no native macOS run was attempted.

## What Was Checked

- Static scan of dependencies and imports.
- Linux audit compiled Python files successfully but dependency resolution failed at `pywin32`.

The same `pywin32` dependency is expected to block macOS installation.

## macOS Blockers

- `pywin32` is an unconditional dependency.
- `hotturkey.cli` imports `win32event` at module import time.
- `run.py` imports `win32api`, `win32event`, and `winerror` at module import time.
- Focus/window detection uses `win32gui` and `win32process`.
- Idle detection uses `ctypes.windll.user32` and `kernel32`.
- Popup and tray actions shell out to PowerShell/cmd.
- Autostart docs are Windows Task Scheduler oriented.

## Potentially Portable Pieces

- Budget state logic.
- Game catalog parsing for Steam/Epic/Legendary may be partially portable after adding macOS install locations.
- Some plotting/reporting helpers.

## Likely Changes Needed

- Mark `pywin32` as Windows-only with environment markers.
- Move all Win32 imports behind platform adapters.
- Make CLI import lazily so pure commands/tests can run without Win32 modules.
- Add macOS focus detection:
  - Accessibility permission flow
  - NSWorkspace active app
  - CGWindow APIs for title/process details
- Add macOS idle detection:
  - IOKit HID idle time or equivalent
- Add macOS notifications:
  - `osascript`
  - terminal-notifier
  - or a native app wrapper
- Add LaunchAgent autostart docs.

## Suggested macOS Scope

Treat this as a port, not a setup task. Start with pure budget CLI and notification-only warnings before attempting full focus tracking.
