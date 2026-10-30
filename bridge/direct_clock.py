"""Exact standalone local-clock questions only; never routes actions."""
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

TIME = {"what time is it", "what's the time", "what is the time", "tell me the time", "what time is it now"}
DATE = {"what's today's date", "what is today's date", "what is the date today", "what's the date today", "what is the date", "what's the date", "what day is it", "what day is it today"}

def direct_clock(text, *, now=None):
    # Only whitespace/case, curly apostrophe, one terminal ASR punctuation mark.
    # Quotes, compound requests, foreign places, timers and followups fall through.
    normalized = re.sub(r"\s+", " ", text.strip().lower().replace("’", "'"))
    normalized = re.sub(r"[?.!]$", "", normalized)
    if normalized not in TIME | DATE:
        return None
    try:
        zone = ZoneInfo(os.getenv('R1_TIMEZONE', 'America/Chicago'))
    except (ZoneInfoNotFoundError, ValueError):
        return None  # Bad configuration must not produce a wrong local answer.
    if now is not None and now.tzinfo is None:
        raise ValueError('aware_clock_required')
    clock = datetime.now(zone) if now is None else now.astimezone(zone)
    if normalized in TIME:
        return f"It's {clock.hour % 12 or 12}:{clock.minute:02d} {'AM' if clock.hour < 12 else 'PM'} {clock.tzname()}."
    return f"Today is {clock.strftime('%A, %B')} {clock.day}, {clock.year}."
