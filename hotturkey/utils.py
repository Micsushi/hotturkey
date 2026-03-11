def format_mmss(seconds: float) -> str:
    """Format a number of seconds as MM:SS (e.g. 924 -> '15:24')."""
    total = max(0, int(seconds))
    minutes = total // 60
    secs = total % 60
    return f"{minutes}:{secs:02d}"

