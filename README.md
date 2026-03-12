# HotTurkey

A Windows screen-time enforcer: tracks Steam games and browser sites (e.g. YouTube), then nags you with escalating terminal popups when you go over your allowed time.

<hr style="border: 5px solid black;">

## How it works

- **Budget** : Time allowances (adjustable, default 1 hour). While a game or tracked site is focused, time is subtracted. When you switch away, budget recovers at half speed (e.g. 2 hours idle ≈ 1 hour back).
  - **Recovery rate** (adjustable, default 0.5 of consumption rate)
- **Overtime** : When budget hits 0 you enter overtime. A separate **overtime debt** is tracked and must be paid down before normal budget refills.
  - **L1** popup when you first hit 0.
  - **L2** at 50% of your budget in overtime (e.g. +30 min on a 60 min budget).
  - **L3, L4, …** at halved steps (e.g. +15 min, +7.5 min, …). Each level shows a full-screen red warning until you close it.
- **Max budget Cap** : Recovery never pushes budget above the cap on its own (can use the CLI to go over the limit)

## What it tracks

- **Steam games** : Focused window must be a process under Steam and the child processes are scanned periodically so new games should get added to the system.
- **Tracked sites** : YouTube and other sites in browsers like Brave/Chrome/Firefox/Edge, when that tab is the active window. Add sites/browsers in `config.py`. (Have not figured out how to track it when the videos are running unfortunately)
- **Bonus sites** : Sites that give you bonus recovery to budget (adjustable, default x2 multiplier) e.g. LeetCode

### AFK (idle)

- **AFK Timer**: no keyboard/mouse input for the configured time (adjustable, default 5 minutes), freezes all timers except for the tracked sites like youtube since it's common to no do anything while a video is playing. Timer also applys to idling or doing something on other sites such that at max 5 min of budget will be added back if you are not doing anything

<hr style="border: 5px solid black;">

## Setup

1. **Python 3.8+** and find its path. In PowerShell you can run:

   ```powershell
   where python
   ```

   Then copy the full path you want to use (e.g. `C:\Users\you\AppData\Local\Programs\Python\Python313\python.exe`).
2. **Clone** the repo and open a terminal in the project folder.
3. **Install the package** (deps + `hotturkey` command) in the project folder:
   ```powershell
   & "C:\Path\To\Your\Python\python.exe" -m pip install -e .
   ```
   After this you can use `hotturkey status`, `hotturkey extra 30`, etc. instead of `python -m hotturkey.cli ...`.

## Running

You can start HotTurkey either via Python or the installed CLI:

```text
python run.py
```

or, after the setup command above you can just run this in any terminal that is in that python env and your python scripts folder is in your path:

```text
ht run
```

Both commands start a **background process** and exit; you can close the terminal. HotTurkey keeps running.

- **Tray icon** (near the clock): green → yellow → orange → red as budget drops. Hover for remaining time and current activity.
- **Logs** : `%USERPROFILE%\.hotturkey\hotturkey.log`. Right-click tray → **Show logs** to tail it.

**Restart with new code** : Run `python run.py` again. The current instance is asked to exit; after it shuts down, a new one starts (single instance, no duplicate tray).

**Tray menu:** Status | Show logs | Quit.

<hr style="border: 5px solid black;">

## CLI

In a **separate** terminal (after `pip install -e .`):

| Command | Effect |
|--------|--------|
| `ht status` | Show budget, overtime debt, activity, session time, overtime level. |
| `ht extra 30` | Add 30 minutes. Positive time clears overtime debt first, then adds to budget. |
| `ht extra -10` | Remove 10 minutes from budget; if that would go below 0, the rest becomes overtime debt. |
| `ht set 30` | Set budget to 30 minutes remaining and clear overtime. |
| `ht set -15` | Set budget to 0 and overtime debt to 15 minutes. |
| `ht set 0` | Set both budget and overtime to 0. |
| `ht stop` | Ask the running HotTurkey background process to exit. |
| `ht morelog` | Switch log level to DEBUG (verbose, includes `[PERF]` timing) for the running app and future runs. |
| `ht lesslog` | Switch log level back to INFO (normal, concise logs) for the running app and future runs. |

Changes are applied on the next poll when the app is running. 

## Auto-start with Windows start

1. `Win + R` → `shell:startup` → Enter.
2. New shortcut → Target: `"C:\Path\To\Python\python.exe" "C:\Path\To\hotturkey\run.py"`.
3. Name it e.g. HotTurkey. Optionally set **Start in** to the project folder and **Run** to Minimized.

<hr style="border: 5px solid black;">

## Dev commands (tests & lint)

After `pip install -e .` you get a few helper commands:

- **Run tests**

  ```powershell
  ht-test
  ```

  (Equivalent to `python -m pytest -v`.)

- **Run lint**

  ```powershell
  ht-lint
  ```

  (Equivalent to `python -m pylint hotturkey/ --rcfile=pyproject.toml`.)

- **Run both (CI-style)**

  ```powershell
  ht-ci
  ```

  which runs lint then tests, matching what the GitHub Action does.

