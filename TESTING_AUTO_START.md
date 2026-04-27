# Testing Auto-Restart (Auto-Renew)

To verify that HotTurkey automatically restarts if it crashes or is closed:

## 1. Configure the Trigger
1.  Open **Task Scheduler** (Windows Search: "Task Scheduler").
2.  Find the task named **`Ht start`**.
3.  Double-click it → **Triggers** tab → Select the trigger → **Edit**.
4.  Check **Repeat task every:** and set it to **1 minute** for testing.
5.  Click OK/Save.

## 2. Perform the Test
1.  Find the HotTurkey icon in your system tray (bottom right, check the `^` overflow menu).
2.  Right-click the icon and click **Quit**.
3.  Wait for the next minute mark on your system clock (e.g., if it's 12:04:15, wait until 12:05:00).

## 3. Verify
1.  The turkey icon should reappear in your system tray automatically.
2.  There should be **no console windows or popups** during this process (it is entirely silent).
3.  (Optional) Check the log: `Get-Content "$env:USERPROFILE\.hotturkey\hotturkey.log" -Tail 20`. You should see a `[COMMAND] start: app started.` entry.

## 4. Cleanup
1.  Go back to Task Scheduler.
2.  Change the **Repeat task every:** back to **2 hours** (or your preferred interval) to prevent unnecessary polling.
