# pyright: reportMissingImports=false

from hotturkey.db import query_daily_total

_CATEGORY_SPEC = [
    ("gaming_s", "Gaming", "#4e79a7"),
    ("entertainment_s", "Entertainment", "#f28e2b"),
    ("social_s", "Social", "#e15759"),
    ("bonus_sites_s", "Bonus sites", "#76b7b2"),
    ("bonus_apps_s", "Bonus apps", "#59a14f"),
    ("other_apps_s", "Other", "#b07aa1"),
]


def _fmt_hm(seconds):
    s = max(0, int(seconds or 0))
    h, m = divmod(s, 3600)
    m = m // 60
    return f"{h}:{m:02d}"


def _hours(seconds):
    return float(seconds or 0) / 3600.0


def _load_mpl():
    try:
        import matplotlib

        matplotlib.use("TkAgg")
        import matplotlib.pyplot as plt

        return matplotlib, plt
    except ImportError as exc:
        raise ImportError(
            "Charts require matplotlib. Install with: pip install matplotlib"
        ) from exc


def _build_pie(fig, ax, row):
    keys = [k for k, _, _ in _CATEGORY_SPEC]
    total = sum(row.get(k, 0) or 0 for k in keys)
    if total <= 0:
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
        return None

    labels = []
    sizes = []
    colors = []
    raw_seconds = []
    for key, lab, col in _CATEGORY_SPEC:
        v = row.get(key, 0) or 0
        if v > 0:
            labels.append(lab)
            sizes.append(_hours(v))
            colors.append(col)
            raw_seconds.append(v)

    wedges, _, _ = ax.pie(
        sizes,
        labels=labels,
        colors=colors,
        autopct=lambda p: f"{p:.0f}%" if p >= 5 else "",
        startangle=90,
        counterclock=False,
    )
    ax.set_title(f"Daily breakdown — {row['date']}  (total {_fmt_hm(total)})")

    annot = ax.annotate(
        "",
        xy=(0, 0),
        fontsize=11,
        fontweight="bold",
        ha="center",
        va="center",
        bbox={"boxstyle": "round,pad=0.4", "fc": "white", "ec": "gray", "alpha": 0.95},
    )
    annot.set_visible(False)

    def on_hover(event):
        if event.inaxes != ax:
            if annot.get_visible():
                annot.set_visible(False)
                fig.canvas.draw_idle()
            return
        for i, wedge in enumerate(wedges):
            if wedge.contains_point([event.x, event.y]):
                pct = sizes[i] / sum(sizes) * 100
                annot.set_text(f"{labels[i]}\n{_fmt_hm(raw_seconds[i])}  ({pct:.0f}%)")
                theta = (wedge.theta1 + wedge.theta2) / 2
                import math

                r = 0.45
                x = r * math.cos(math.radians(theta))
                y = r * math.sin(math.radians(theta))
                annot.set_position((x, y))
                annot.xy = (x, y)
                annot.set_visible(True)
                fig.canvas.draw_idle()
                return
        if annot.get_visible():
            annot.set_visible(False)
            fig.canvas.draw_idle()

    fig.canvas.mpl_connect("motion_notify_event", on_hover)
    return annot


def _build_bar(fig, ax, rows):
    chron = list(reversed(rows))
    dates = [r["date"] for r in chron]
    n = len(dates)

    bar_groups = []
    bottom = [0.0] * n
    for key, lab, col in _CATEGORY_SPEC:
        heights = [_hours(r.get(key, 0)) for r in chron]
        raw_secs = [r.get(key, 0) or 0 for r in chron]
        if any(h > 0 for h in heights):
            bars = ax.bar(
                dates, heights, bottom=bottom, label=lab, color=col, width=0.65
            )
            bar_groups.append((bars, lab, raw_secs))
            bottom = [bottom[i] + heights[i] for i in range(n)]

    ax.set_ylabel("Hours")
    ax.set_title(f"Stacked daily totals ({n} day{'s' if n != 1 else ''})")
    ax.legend(loc="upper left", bbox_to_anchor=(1.02, 1), fontsize=9)
    ax.set_ylim(bottom=0)

    import matplotlib.pyplot as plt

    plt.setp(ax.xaxis.get_majorticklabels(), rotation=40, ha="right")

    annot = ax.annotate(
        "",
        xy=(0, 0),
        xytext=(0, 12),
        textcoords="offset points",
        fontsize=10,
        fontweight="bold",
        ha="center",
        va="bottom",
        bbox={"boxstyle": "round,pad=0.3", "fc": "white", "ec": "gray", "alpha": 0.95},
    )
    annot.set_visible(False)

    def on_hover(event):
        if event.inaxes != ax:
            if annot.get_visible():
                annot.set_visible(False)
                fig.canvas.draw_idle()
            return
        for bars, lab, raw_secs in bar_groups:
            for idx, bar in enumerate(bars):
                if bar.contains(event)[0]:
                    secs = raw_secs[idx]
                    annot.set_text(f"{lab}\n{_fmt_hm(secs)}")
                    x = bar.get_x() + bar.get_width() / 2
                    y = bar.get_y() + bar.get_height()
                    annot.xy = (x, y)
                    annot.set_visible(True)
                    fig.canvas.draw_idle()
                    return
        if annot.get_visible():
            annot.set_visible(False)
            fig.canvas.draw_idle()

    fig.canvas.mpl_connect("motion_notify_event", on_hover)
    return annot


def show_pie(rows, pie_date=None):
    _, plt = _load_mpl()

    pie_row = None
    if pie_date:
        pie_row = query_daily_total(pie_date)
    elif rows:
        pie_row = rows[0]

    if not pie_row:
        print("\n  No data to plot.\n")
        return

    fig, ax = plt.subplots(figsize=(7, 6))
    _build_pie(fig, ax, pie_row)
    try:
        fig.canvas.manager.set_window_title("HotTurkey — Pie chart")
    except AttributeError:
        pass

    print("\n  Hover over a slice to see HH:MM. Close the window to return.\n")
    plt.show()


def show_bar(rows):
    _, plt = _load_mpl()

    if not rows:
        print("\n  No data to plot.\n")
        return

    chron = list(reversed(rows))
    n = len(chron)
    fig, ax = plt.subplots(figsize=(max(8.0, n * 0.85), 5.5))
    _build_bar(fig, ax, rows)
    fig.tight_layout()
    try:
        fig.canvas.manager.set_window_title("HotTurkey — Bar chart")
    except AttributeError:
        pass

    print("\n  Hover over a bar segment to see HH:MM. Close the window to return.\n")
    plt.show()


def show_both(rows, pie_date=None):
    _, plt = _load_mpl()

    pie_row = None
    if pie_date:
        pie_row = query_daily_total(pie_date)
    elif rows:
        pie_row = rows[0]

    has_pie = (
        pie_row
        and sum((pie_row or {}).get(k, 0) or 0 for k, _, _ in _CATEGORY_SPEC) > 0
    )
    has_bar = bool(rows)

    if not has_pie and not has_bar:
        print("\n  No data to plot.\n")
        return

    if has_pie and has_bar:
        fig, (ax_pie, ax_bar) = plt.subplots(1, 2, figsize=(15, 6))
        _build_pie(fig, ax_pie, pie_row)
        _build_bar(fig, ax_bar, rows)
    elif has_pie:
        fig, ax_pie = plt.subplots(figsize=(7, 6))
        _build_pie(fig, ax_pie, pie_row)
    else:
        chron = list(reversed(rows))
        n = len(chron)
        fig, ax_bar = plt.subplots(figsize=(max(8.0, n * 0.85), 5.5))
        _build_bar(fig, ax_bar, rows)

    fig.tight_layout()
    try:
        fig.canvas.manager.set_window_title("HotTurkey — Activity charts")
    except AttributeError:
        pass

    print("\n  Hover over chart elements to see HH:MM. Close the window to return.\n")
    plt.show()
