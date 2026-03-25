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

**1. Check Python (3.8 or newer)**

```powershell
python --version
```

If that fails, try:

```powershell
py -3 --version
```

**2. Clone the repo** and open a terminal **inside the project folder**.

**3. Install**

```powershell
python -m pip install -e .
```

That installs HotTurkey’s libraries and adds **`ht`** and **`hotturkey`** (same program) plus dev helpers like **`ht-test`** / **`hotturkey-test`** into your Python **Scripts** folder.

**4. Use `ht` or `hotturkey` from any folder (optional)**

Windows only finds those commands if the **`Scripts`** folder is on your **Path**.

1. Open **Settings** → **System** → **About** → **Advanced system settings**.
2. Click **Environment Variables**.
3. Under your user name, select **Path** → **Edit** → **New**.
4. Paste the path to your **Scripts** folder, for example
   `C:\Users\YourName\AppData\Local\Programs\Python\Python313\Scripts`
   In PowerShell you can see where `pip` lives (that folder is **Scripts**):

```powershell
(Get-Command pip).Source
```

5. Save, then **open a new terminal**. Now `ht run`, `hotturkey status`, etc. work from any directory.

If you do **not** add **Scripts** to Path, you can still run the same commands like this:

```powershell
python -m hotturkey.cli run
python -m hotturkey.cli status
```

**If `python` is not on Path when you install**

Use the full path to `python.exe`:

```powershell
& "C:\Path\To\python.exe" -m pip install -e .
```

## Running

Start HotTurkey in either of these ways:

```text
python run.py
```

```text
ht run
```

```text
hotturkey run
```

`ht run` and `hotturkey run` do the same thing; both need **Scripts** on Path (Setup step 4). Otherwise use `python run.py` or `python -m hotturkey.cli run`.

Both start HotTurkey in the **background** and then the terminal can close; the app keeps running.

- **Tray icon** (near the clock): green → yellow → orange → red as budget drops. Hover for remaining time and current activity.
- **Logs** : `%USERPROFILE%\.hotturkey\hotturkey.log`. Right-click tray → **Show logs** to tail it.

**Restart with new code** : Run `python run.py` again. The current instance is asked to exit; after it shuts down, a new one starts (single instance, no duplicate tray).

**Tray menu:** Status | Show logs | Quit.

<hr style="border: 5px solid black;">

## CLI

In another terminal, after install. If **Scripts** is on Path, use the commands in the table. You can type **`hotturkey` instead of `ht`** for every command (for example `hotturkey status` and `ht status` are the same). If **Scripts** is not on Path, use `python -m hotturkey.cli` plus the same subcommand (example: `python -m hotturkey.cli status`).

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

After `pip install -e .` you get helper commands. Each has a short name and a `hotturkey-*` alias (`ht-test` / `hotturkey-test`, and so on).

- **Run tests** — `ht-test` or `hotturkey-test` (same as `python -m pytest -v`).

  ```powershell
  ht-test
  ```

- **Run lint** — `ht-lint` or `hotturkey-lint`.

  ```powershell
  ht-lint
  ```

- **Run both (CI-style)** — `ht-ci` or `hotturkey-ci` (lint then tests, like the GitHub Action).

  ```powershell
  ht-ci
  ```

