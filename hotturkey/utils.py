def format_duration(seconds: float) -> str:
    """Format seconds as MM:SS, or H:MM:SS when >= 1 hour (e.g. 924 -> '15:24', 3661 -> '1:01:01')."""
    total = max(0, int(seconds))
    if total >= 3600:
        hours = total // 3600
        remainder = total % 3600
        minutes = remainder // 60
        secs = remainder % 60
        return f"{hours}:{minutes:02d}:{secs:02d}"
    minutes = total // 60
    secs = total % 60
    return f"{minutes}:{secs:02d}"
