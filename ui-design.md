# UI Design

HotTurkey currently uses fullscreen terminal warnings and a system tray. A
settings or history dashboard is planned but not implemented.

## Required Source

- Visual tokens and detailed rules: `DESIGN.md`
- Popup implementation: `hotturkey/`

## Rules

- Preserve the existing DarkRed and white fullscreen interruption.
- Keep overtime state, duration, escalation level, and recovery time explicit.
- Reserve red for overtime and enforcement states.
- Keep future settings/history UI operational, warm-dark, and free of
  decorative gradients.
- Update `DESIGN.md` when exact stable tokens change.

OpenSpec change `design.md`, if introduced later, remains technical design and
does not replace this UI contract.
