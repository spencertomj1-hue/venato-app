"""
App settings: settings.json in the data folder, and the timetable day's hours read from it.
"""

import json

from .database import bump_version, data_dir, data_version


# Timetable: half-hour slots from day_start to day_end (default 07:00 to 01:00 the next day,
# 36 slots). Set in Settings -> Region; slot_count() and first_min() follow them.
DAY_START, DAY_END = 7, 1           # defaults (hours); an end at or before the start is the next morning


def settings_path():
    return data_dir() / "settings.json"


def load_settings():
    try:
        return json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def ai_enabled():
    """Is the optional Claude assistant switched on? (Off on new installs unless chosen in setup;
    on for installs from before the switch existed.)"""
    return bool(load_settings().get("ai_enabled", True))


def save_settings(**changes):
    settings = {**load_settings(), **changes}
    settings_path().parent.mkdir(parents=True, exist_ok=True)
    settings_path().write_text(json.dumps(settings, indent=2), encoding="utf-8")
    bump_version()
    return settings


def day_hours():
    """(start hour, end hour) of a timetable day; an end at or before the start is the next morning."""
    version = data_version()           # (slot_of asks on every call, so settings.json is re-read only after a write)
    if _hours[0] != version:
        _hours[:] = [version, _read_day_hours()]
    return _hours[1]


_hours = [None, None]                  # [data_version() when read, (start, end)]


def _read_day_hours():
    s = load_settings()
    start, end = s.get("day_start", DAY_START), s.get("day_end", DAY_END)
    ok = lambda h: isinstance(h, int) and 0 <= h <= 23
    return (start, end) if ok(start) and ok(end) and day_length(start, end) >= MIN_DAY_HOURS else (DAY_START, DAY_END)


MIN_DAY_HOURS = 6


def day_length(start, end):
    """Hours in a timetable day from start to end (wrapping past midnight; equal = a full 24 hours)."""
    return (end - start) % 24 or 24
