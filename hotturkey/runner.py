# runner.py -- Launches the HotTurkey background process.
# Called by cli.py when the user runs "hotturkey run".
# The actual monitor loop and tray logic live in run.py (project root).

import os
import subprocess
import sys


def launch():
    """Spawn the HotTurkey background process via run.py and exit.

    Sets HOTTURKEY_DETACHED=1 so the spawned process knows it's running in
    the background. The actual monitor loop and tray are handled by run.py.
    """
    if os.environ.get("HOTTURKEY_DETACHED") == "1":
        return

    env = os.environ.copy()
    env["HOTTURKEY_DETACHED"] = "1"
    package_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(package_dir)
    run_path = os.path.join(root_dir, "run.py")
    subprocess.Popen(
        [sys.executable, run_path],
        cwd=root_dir,
        env=env,
        creationflags=(
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        ),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print(
        "HotTurkey started (or is already running) in background. "
        "You can close this terminal."
    )
    print("Right-click the tray icon for Status, Show logs, or Quit.")
    sys.exit(0)
