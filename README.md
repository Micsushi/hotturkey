# HotTurkey

A screen time enforcer that tracks Steam games and tracked sites (YouTube, etc.) in your browser, then nags you with escalating terminal popups when you've played too long.

## How it works

- You get a **1-hour budget** of play/watch time.
- At **30 minutes** used, a brief flash reminder appears for 2 seconds then auto-closes.
- At **1 hour** (budget hits 0), a full-screen red terminal popup appears and stays until you close it.
- If you keep going, popups escalate: **30 min → 15 min → 7.5 min → 3.75 min...** until you stop.
- When you stop and close the tracked app, budget recovers at a 1:2 ratio (2 hours idle = full 1hr recovery).
- Budget never exceeds 1 hour through recovery alone. Use `hotturkey extra` to go beyond that.

## What it tracks

- **Steam games** — any game launched through Steam, only counted when the game window is focused.
- **Tracked sites in browsers** — by default YouTube, in Brave/Chrome/Firefox/Edge. Only counted when the tab is the active focused window. You can add more sites or browsers in `hotturkey/config.py`.

## Setup

1. Make sure you have **Python 3.8+** installed. Open a terminal and check:
   ```
   python --version
   ```

2. Clone or download this repo, then open a terminal in the project folder:
   ```
   cd C:\Users\sushi\Documents\Github\hotturkey
   ```

3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

## Running

Start the app:
```
python run.py
```

The app spawns a **background process** and exits. You can close the terminal immediately — HotTurkey keeps running.

You'll see:
- A **system tray icon** near your clock (bottom-right). The circle is green (plenty of budget), yellow (10-30 min left), orange (<10 min), or red (budget depleted).
- Logs saved to `C:\Users\<you>\.hotturkey\hotturkey.log`.

**Right-click the tray icon** for:
- **Status** — quick popup with budget and activity info
- **Show logs** — opens a terminal with live log output (tails the log file)
- **Quit** — stops the app

## CLI commands

Open a **separate** terminal (keep `run.py` running in the other one):

**Check your remaining budget:**
```
python -m hotturkey.cli status
```

**Add extra time (only way to go above 1hr):**
```
python -m hotturkey.cli extra 30
```
This adds 30 minutes. The running app picks it up within 5 seconds.

## Testing it yourself

Here's how to verify each feature works:

### 1. Basic startup
```
python run.py
```
- You'll see "HotTurkey started in background. You can close this terminal."
- Confirm a green circle appears in the system tray.
- Hover over it — tooltip should say "HotTurkey: 60:00 remaining".
- Right-click → **Show logs** to see live log output in a new terminal.

### 2. YouTube detection
- Open Brave (or Chrome/Firefox/Edge) and go to youtube.com.
- Make sure the YouTube tab is focused (click on it).
- Watch the terminal logs — you should see `[WATCHING] YouTube (Brave) is focused`.
- The tray tooltip should start counting down.
- Alt-tab away from the browser — logs should stop showing `[WATCHING]` and budget should start recovering.

### 3. Steam game detection
- Launch any Steam game.
- With the game window focused, check the logs — you should see `[GAMING] <game>.exe is focused`.
- Alt-tab out of the game — tracking should pause.

### 4. Status check
In a separate terminal:
```
python -m hotturkey.cli status
```
You should see your remaining budget, what's being tracked, and session time.

### 5. Gentle reminder (30-min mark)
- To test without waiting 30 min, temporarily edit `hotturkey/config.py` and set `GENTLE_REMINDER_AFTER_SECONDS = 10`.
- Start `run.py`, open YouTube, and wait 10 seconds.
- A small terminal window should flash briefly and auto-close.
- Reset the config value after testing.

### 6. Overtime popup (budget = 0)
- To test quickly, edit `config.py` and set `MAX_PLAY_BUDGET_SECONDS = 30` (30 seconds).
- Start `run.py`, open YouTube, and wait ~30 seconds.
- A maximized red terminal should appear saying "BUDGET DEPLETED".
- Reset the config values after testing.

### 7. Extra time
While the app is running and your budget is at 0:
```
python -m hotturkey.cli extra 5
```
- The popups should stop for 5 minutes as your budget is now 5:00 again.

### 8. State persistence
- While the app is running with some budget used, close it (Ctrl+C or tray Quit).
- Start it again with `python run.py`.
- Check the tray tooltip — it should show the same budget you had before, not a fresh 60:00.

## Files

```
hotturkey/
  hotturkey/
    __init__.py     — marks it as a Python package
    config.py       — all tunable constants (budget, intervals, tracked sites)
    state.py        — data model and JSON persistence
    monitor.py      — detection (Steam + browser) and budget logic
    popup.py        — flash and fullscreen popup spawning
    tray.py         — system tray icon
    logger.py       — logging to console + file
    cli.py          — CLI commands (status, extra)
  run.py            — main entry point
  requirements.txt  — Python dependencies
```

## State storage

All state is saved to `C:\Users\<you>\.hotturkey\`:
- `state.json` — budget, session info, timestamps (updated every 5 seconds)
- `hotturkey.log` — log history

## Configuration

Edit `hotturkey/config.py` to change:
- `MAX_PLAY_BUDGET_SECONDS` — total allowed time (default: 3600 = 1hr)
- `BUDGET_RECOVERY_PER_SECOND_IDLE` — recovery speed (default: 0.5, meaning 2hr idle = full recovery)
- `TRACKED_BROWSERS` — list of browser names to monitor
- `TRACKED_SITES` — list of site names to monitor
- `GENTLE_REMINDER_AFTER_SECONDS` — when the gentle flash popup appears
- `FIRST_OVERTIME_POPUP_DELAY_SECONDS` — first overtime popup delay
