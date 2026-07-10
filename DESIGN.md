---
name: HotTurkey
version: alpha
description: Windows screen-time enforcer. Current UI is fullscreen terminal popups (PowerShell, DarkRed/White) and a system tray icon. Future settings/history dashboard should use Foundry warm-dark base extended here.
colors:
  popup-bg: "#8B0000"
  popup-text: "#FFFFFF"
  popup-warning-bg: "#8B6914"
  popup-warning-text: "#FFFFFF"
  future-bg: "#0E0D0B"
  future-surface: "#17150F"
  future-surface-raised: "#211E17"
  future-border: "#2C2920"
  future-text-primary: "#EDE6DA"
  future-text-secondary: "#9A9084"
  future-accent: "#CC5F2A"
  future-accent-hover: "#E06B30"
  future-positive: "#5A9E65"
  future-negative: "#B84040"
  future-warning: "#C49A3C"
typography:
  popup:
    fontFamily: "Cascadia Mono, Consolas, monospace"
  future-body:
    fontFamily: "Inter"
    fontSize: "0.9375rem"
    lineHeight: "1.6"
  future-mono:
    fontFamily: "JetBrains Mono"
    fontSize: "0.875rem"
rounded:
  future-sm: "4px"
  future-md: "6px"
spacing:
  sm: "8px"
  md: "16px"
  lg: "24px"
components:
  popup-line:
    backgroundColor: "{colors.popup-bg}"
    textColor: "{colors.popup-text}"
    padding: "padded to fill terminal width"
  future-card:
    backgroundColor: "{colors.future-surface}"
    rounded: "{rounded.future-md}"
    padding: "16px 20px"
  future-button-primary:
    backgroundColor: "{colors.future-accent}"
    textColor: "#000000"
    rounded: "{rounded.future-sm}"
    padding: "8px 16px"
---

## Overview

Two UI surfaces. One exists. One is planned.

**Existing : Terminal popup:**
Fullscreen PowerShell window. DarkRed background, white text. Shows when overtime is detected. Must be impossible to ignore. No subtlety.

**Planned : Settings/history dashboard:**
If a settings or history viewer is ever built, use the Foundry warm-dark base (tokens prefixed `future-` above are the target). A tray menu and optional system dialog are also acceptable alternatives to a full GUI.

## Popup Design

The popup is a fullscreen PowerShell terminal window. No HTML, no widgets : pure console text.

Design rules for popup content:
- **Background:** `DarkRed` (PowerShell color name) : bright enough to break through game fullscreen
- **Text:** `White` : maximum contrast
- **Layout:** padded lines to fill terminal width, centered message block
- **Content:** overtime duration, escalation level, recovery time, one random message from pool, optional ASCII art
- **Escalation levels:** higher levels = more alarming message content (not more color : color is always DarkRed)
- **No animation, no sound.** The visual interrupt is sufficient.
- Do not add a "dismiss countdown" : user presses any key to close.

Popup line format:
```
[padded to fill width, white on DarkRed]
  Overtime detected. Stop now.

  Overtime: 23m  |  Level: L2
  Next level: L3 in ~7m
  Full recovery: 54m
  Session: 1h 12m on Steam

  [ascii art if available]

  Press any key to close...
[padded to fill width]
```

## Planned Settings UI

If a GUI settings screen is added (web, tkinter, or similar), follow these principles:

- Use Foundry warm-dark palette (the `future-*` tokens above)
- Show: tracked apps list, daily budgets, session history chart, current state at a glance
- Session chart: bar chart, accent color (`#CC5F2A`) for used time, muted for remaining
- Never use red for non-overtime states : red is reserved for the popup only
- Tray icon tooltip should show current budget remaining in plain text

## Do's and Don'ts

**Do:**
- Popup must be DarkRed/White. Never soften the interrupt with amber or gray.
- All duration values: `HH:MM` or `Xh Ym` format, monospace.
- Escalation should change message tone, not color scheme.
- Future GUI: warm dark, single accent, no gradients.

**Don't:**
- No HTML/CSS for the current popup : it's a PowerShell terminal. Don't add a web renderer.
- No animations on popup content : static text only.
- No "snooze" UI element : the popup enforces, it does not negotiate.
- No cold blue/gray/indigo in any future UI : this app is about heat and urgency.
- No dark-mode toggle : Foundry base is dark-only.
