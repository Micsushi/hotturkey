# HotTurkey

## How it works

- You get a **1-hour budget** of play/watch time.
- At **30 minutes**, a brief flash reminder appears.
- At **1 hour** (budget hits 0), a full-screen terminal popup appears.
- If you keep going, popups escalate: **30 min, 15 min, 7.5 min, 3.75 min...** until you stop.
- When you stop, budget recovers at a 1:2 ratio (2 hours idle = full recovery).

## Setup

```
pip install -r requirements.txt
python run.py
```

## CLI

```
hotturkey status       # check remaining budget
hotturkey extra 30     # add 30 minutes of extra time
```
