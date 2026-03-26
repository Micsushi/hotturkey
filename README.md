# HotTurkey

Windows screen-time enforcer. Tracks Steam games and browser sites, then bugs you with escalating popups when you exceed your allowed time.

---

## How It Works

**Budget**: Default 1 hour. Ticks down while a tracked app is focused. Recovers budget when you do something productive

**Overtime**: Starts when budget hits 0. Debt must be paid before budget refills.

| Level | Trigger |
|-------|---------|
| L1 | Budget reaches 0 |
| L2 | 50% of budget into overtime (+30 min on a 60 min budget) |
| L3, L4, … | Halved steps (+15 min, +7.5 min, …) |

Each level shows a full-screen red warning until dismissed.

---

## What It Tracks

- **Steam games**: Any focused process under Steam. Child processes are scanned periodically.
- **Tracked sites**: YouTube, etc. in Brave / Chrome / Firefox / Edge when the tab is the active window. Configure in `config.py`.
- **Bonus sites**: Sites like LeetCode that give extra recovery rate (adjustable).

---

## Setup

### 1. Python 3.8+

```powershell
python --version        # or: py -3 --version
```

### 2. Clone & install

```powershell
git clone https://github.com/Micsushi/hotturkey.git && cd hotturkey
python -m pip install -e .
```

This adds the `ht` / `hotturkey` commands and dev helpers (`ht-test`, `ht-lint`, `ht-ci`) to your Python Scripts folder.

### 3. Add Scripts to PATH *(optional but recommended)*

Required for `ht`/`hotturkey` commands to work from any directory.

1. **Settings → System → About → Advanced system settings → Environment Variables**
2. Edit your user **Path** → add your Scripts folder, e.g.
   `C:\Users\YourName\AppData\Local\Programs\Python\Python313\Scripts`

Find it with:

```powershell
(Get-Command pip).Source
```

3. Open a **new terminal** to pick up the change.

Without PATH, use `python -m hotturkey.cli <subcommand>` instead.

---

## Running

All methods start HotTurkey in the **background**: the terminal can close after.

### With PATH set up (from anywhere)

```powershell
ht run
hotturkey run          # same thing
```

### Without PATH (from the project folder)

```powershell
python run.py
python -m hotturkey.cli run
```

`python run.py` and `python -m hotturkey.cli run` must be run from the project root.

## How to tell it's working

A **tray icon** appears in the bottom-right of your taskbar. If you don't see it, click the **^** arrow in the system tray and look for a small white dot, that's HotTurkey. Would recommend that you drag it onto the taskbar so it stays visible.

The icon changes color as budget drops: green → yellow → orange → red. Hover over it to see remaining time.

**Right-click the icon** to open the tray menu:

- **Status**: current budget and activity
- **Show logs**: this is the best way to keep track of what is happening
- **Quit**: stop HotTurkey

**Restart**: If you run the start command again. Old instance exits, new one launches.

---

## Auto-Start with Windows

1. `Win + R` → `shell:startup` → Enter
2. Create a shortcut with this **Target** (two quoted paths, one space):

```text
"C:\Path\To\python.exe" "C:\Path\To\hotturkey\run.py"
```

3. Optionally set **Start in** to the project folder and **Run** to **Minimized**.
4. Double-click to test: tray icon should appear.

---

## CLI

With PATH: `ht <subcommand>` or `hotturkey <subcommand>` from anywhere.
Without PATH: `python -m hotturkey.cli <subcommand>` from the project folder.

| Command | Effect |
|---------|--------|
| `ht status` | Budget, overtime debt, activity, session time, level |
| `ht extra 30` | Add 30 min (clears debt first, then adds to budget) |
| `ht extra -10` | Remove 10 min (excess becomes debt) |
| `ht set 30` | Set budget to 30 min, clear overtime |
| `ht set -15` | Set budget to 0, debt to 15 min |
| `ht set 0` | Zero both budget and overtime |
| `ht stop` | Stop the background process |
| `ht morelog` | Switch to DEBUG logging |
| `ht lesslog` | Switch back to INFO logging |

Changes apply on the next poll cycle.

### History & charts

Daily totals and per-session history are stored in SQLite at `%USERPROFILE%\.hotturkey\history.db`. The CLI refreshes today’s row from `state.json` when you run these commands so numbers stay in sync with `ht status`.

| Command | Effect |
|---------|--------|
| `ht history` | Table of daily totals (gaming, entertainment, social, bonus sites, bonus apps, other) for the last 7 days |
| `ht history --days 30` | Same, last 30 days |
| `ht history --date 2026-03-25` | List sessions for that date (start/end, activity, mode, duration) |
| `ht history --chart` | ASCII stacked bar per day in the terminal |
| `ht history --plot` | One matplotlib window: pie + stacked bar side by side (requires `matplotlib`; hover slices/segments for **H:MM**) |
| `ht history --date 2026-03-25 --plot` | Sessions table plus charts; pie uses that date |
| `ht pie` | Pie chart for **today** (or latest day in range) |
| `ht pie --date 2026-03-25` | Pie chart for a specific date |
| `ht pie --days 14` | Load data context from last 14 days (pie still targets `--date` or today) |
| `ht bar` | Stacked bar chart for the last 7 days |
| `ht bar --days 30` | Stacked bar for the last 30 days |
| `ht clear-sessions --yes` | Delete **all** rows in the `sessions` table (per-session log only; `daily_totals` unchanged) |

Install dependencies (including matplotlib) with `pip install -e .` from the project folder.

---

## Dev Commands

After `pip install -e .`:

```powershell
ht-test       # run tests (pytest -v)
ht-lint       # run linter
ht-ci         # lint + tests (CI-style)
```

Each also has a `hotturkey-*` alias (e.g. `hotturkey-test`).
