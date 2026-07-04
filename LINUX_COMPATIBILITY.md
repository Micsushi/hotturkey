# Linux Compatibility Notes

Audit date: 2026-07-03

## Status

Not Linux-compatible as an app today. Some pure Python pieces compile, but runtime import and dependency installation fail because the app depends directly on Win32 APIs.

## What Was Tested

Host:

```bash
python3 -m compileall -q hotturkey
```

Result: passed.

Disposable Python 3.12 Docker dependency probe:

```bash
python -m pip install --dry-run -r requirements.txt
```

Result:

- Failed because `pywin32` has no Linux distribution.

Known import failures from read-only probes:

- `import hotturkey.cli` fails with missing `win32event`.
- `import run` fails with missing `win32api`.
- `hotturkey.game_catalog` imports successfully.

Host caveat: `python3-venv` is not installed on this Ubuntu machine.

## Linux Blockers

- `pywin32` is an unconditional dependency.
- `hotturkey.cli` imports `win32event` at module import time.
- `run.py` imports `win32api` and `win32event` at module import time.
- Focus/window detection uses `win32gui` and `win32process`.
- Popup and tray actions shell out to PowerShell/cmd.
- Startup docs and scripts are Windows Task Scheduler oriented.

## Likely Changes Needed

- Mark `pywin32` as Windows-only with environment markers.
- Move Win32 imports behind platform adapters.
- Make CLI import lazily so pure commands/tests can run on Linux.
- Add Linux focus detection:
  - X11: `xdotool`, `xprop`, or Python X11 bindings
  - Wayland: desktop-specific APIs or portal limitations need design
- Add Linux idle detection, likely X11 first.
- Add Linux popup/notification implementation:
  - start with `notify-send`
  - add fullscreen overlay later
- Add Linux autostart docs using systemd user units or XDG autostart.
- Add Linux tray notes for AppIndicator/libayatana dependencies if `pystray` remains.

## Suggested Ubuntu Scope

Start with a limited Linux mode:

- budget engine tests
- game catalog parsing
- CLI status/set/extra commands
- notification-only overtime warnings

Full focus tracking and enforcement should be treated as a separate Linux port.
