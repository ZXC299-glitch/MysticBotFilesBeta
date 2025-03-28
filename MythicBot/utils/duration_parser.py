# utils/duration_parser.py
import re
import datetime

def parse_duration(duration_str: str) -> datetime.timedelta | None:
    """
    Parses a duration string (e.g., "10m", "1h", "2d") into a timedelta.
    Returns None if the format is invalid or duration is out of bounds.
    Maximum duration is 28 days.
    """
    if not isinstance(duration_str, str): # Basic type check
        return None

    match = re.match(r"(\d+)([smhd])$", duration_str.lower()) # Added $ for exact match
    if not match:
        return None

    try:
        value = int(match.group(1))
        unit = match.group(2)
    except ValueError:
        return None # Should not happen with regex, but safety first

    if value <= 0: # Duration must be positive
        return None

    if unit == 's':
        delta = datetime.timedelta(seconds=value)
    elif unit == 'm':
        delta = datetime.timedelta(minutes=value)
    elif unit == 'h':
        delta = datetime.timedelta(hours=value)
    elif unit == 'd':
        delta = datetime.timedelta(days=value)
    else:
        return None # Should not happen

    # Discord timeout limit is 28 days (2419200 seconds)
    if delta > datetime.timedelta(days=28):
        return None # Indicate duration is too long

    return delta