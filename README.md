# HotTurkey

A Windows screen-time enforcer: tracks Steam games and browser sites (e.g. YouTube), then nags you with escalating terminal popups when you go over budget.

## How it works

- **Budget** — Configurable play/watch allowance (default 1 hour). While a game or tracked site is focused, time is subtracted. When you switch away (and you’re not AFK), budget recovers at half speed (e.g. 2 hours idle ≈ 1 hour back).
- **Gentle reminder** — At 30 minutes used (configurable), a short flash reminder appears once per session.
- **Overtime** — When budget hits 0 you enter overtime. A separate **overtime debt** is tracked and must be paid down (by being idle or on bonus sites) before normal budget refills.
  - **L1** popup when you first hit 0.
  - **L2** at 50% of your budget in overtime (e.g. +30 min on a 60 min budget).
  - **L3, L4, …** at halved steps (e.g. +15 min, +7.5 min, …). Each level shows a full-screen red warning until you close it.
- **Cap** — Recovery never pushes budget above the cap on its own; use the CLI to add time or set budget/overtime directly.

## What it tracks

- **Steam games** — Focused window must be a process under Steam (process tree is walked; launchers like PioneerGame.exe are handled). Steam’s child processes are scanned periodically so new games are learned without scanning the whole system.
- **Tracked sites** — YouTube and others in Brave/Chrome/Firefox/Edge, when that tab is the active window. Add sites/browsers in `config.py`.
- **Bonus sites** — e.g. LeetCode: focused time **recovers** budget faster instead of consuming it.

### AFK (idle)

- AFK = no keyboard/mouse input for the configured threshold (default 5 minutes).
- **Steam games**: while AFK, budget is frozen (no consumption) so idling in menus doesn’t count.
- **Tracked sites**: still consume and build overtime (watching counts).
- **Idle / bonus**: recovery is frozen so you can’t farm time by walking away.

## Setup

1. **Python 3.8+** — Run `python --version` (or use your full interpreter path if needed).
2. **Clone** the repo and open a terminal in the project folder.
3. **Install deps** for the same Python you’ll run with:
   ```powershell
   & "C:\Path\To\Your\Python\python.exe" -m pip install -r ".\requirements.txt"
   ```

## Running

```text
python run.py
```

The app starts a **background process** and exits; you can close the terminal. HotTurkey keeps running.

- **Tray icon** (near the clock): green → yellow → orange → red as budget drops. Hover for remaining time and current activity.
- **Logs** — `%USERPROFILE%\.hotturkey\hotturkey.log`. Right-click tray → **Show logs** to tail it.

**Restart with new code** — Run `python run.py` again. The current instance is asked to exit; after it shuts down, a new one starts (single instance, no duplicate tray).

**Tray menu:** Status | Show logs | Quit.

## CLI

In a **separate** terminal:

| Command | Effect |
|--------|--------|
| `python -m hotturkey.cli status` | Show budget, overtime debt, activity, session time, overtime level. |
| `python -m hotturkey.cli extra 30` | Add 30 minutes. Positive time clears overtime debt first, then adds to budget. |
| `python -m hotturkey.cli extra -10` | Remove 10 minutes from budget; if that would go below 0, the rest becomes overtime debt. |
| `python -m hotturkey.cli set 30` | Set budget to 30 minutes remaining and clear overtime. |
| `python -m hotturkey.cli set -15` | Set budget to 0 and overtime debt to 15 minutes. |
| `python -m hotturkey.cli set 0` | Set both budget and overtime to 0. |

Changes are applied on the next poll when the app is running.

## Testing

- **Start** — `python run.py` → tray icon appears; hover shows e.g. `60:00 remaining`.
- **YouTube** — Focus a YouTube tab in a supported browser → logs show `[WATCHING] YouTube (Brave)` (or similar); tray countdown runs; alt-tab away → recovery.
- **Steam** — Focus a Steam game → `[GAMING] <game>.exe is focused`; alt-tab out → tracking pauses.
- **Status** — `python -m hotturkey.cli status` shows budget, overtime, activity, session.
- **Gentle reminder** — Set `GENTLE_REMINDER_AFTER_SECONDS = 10` in config, run, focus YouTube 10 s → flash popup.
- **Overtime popup** — Set `MAX_PLAY_BUDGET_SECONDS = 30`, run, stay on YouTube ~30 s → red “BUDGET DEPLETED” (L1); keep going for L2/L3.
- **Extra time** — With budget at 0: `python -m hotturkey.cli extra 5` → overtime (if any) cleared first, then budget gets 5 minutes.
- **Persistence** — Quit via tray, start again → same budget/overtime (and startup log shows overtime debt if any).

## Files

- **run.py** — Entry point; starts background process and tray.
- **hotturkey/** — Package: `config.py` (tunables), `state.py` (persistence), `monitor.py` (detection + budget/overtime), `popup.py` (reminders + overtime popups), `tray.py` (icon + menu), `logger.py`, `cli.py` (status, extra, set).
- **requirements.txt** — Python dependencies.

## State and config

**State dir:** `%USERPROFILE%\.hotturkey\`

- `state.json` — Budget, overtime debt, session, timestamps.
- `extra.json` / `set.json` — Pending CLI `extra` / `set` for the next poll.
- `run.pid` — Current process PID for clean restart.
- `hotturkey.log` — Log file.

**Config** (`hotturkey/config.py`): budget cap, recovery rate, poll interval, AFK threshold, tracked/bonus sites and browsers, gentle-reminder timing, overtime level thresholds.

## Auto-start (optional)

1. `Win + R` → `shell:startup` → Enter.
2. New shortcut → Target: `"C:\Path\To\Python\python.exe" "C:\Path\To\hotturkey\run.py"`.
3. Name it e.g. HotTurkey. Optionally set **Start in** to the project folder and **Run** to Minimized.
