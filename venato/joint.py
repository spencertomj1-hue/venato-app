"""
The joint calendar: the user's Outlook calendar and their partner's, side by side.

Privacy rule (both people): an event shows only as blocked-out time, unless its
title contains "!", e.g. "Dinner with mum!" - then its title shows (without the
"!"). Nothing else (location, notes, attendees) is ever kept.

The rule is applied as the calendar is read, so a hidden event's title never
reaches the database or the disk: joint_events holds only times, and titles of
"!" events. The partner's link lives only in the system's secret store (like the
user's own Outlook link), and is never logged or shown.

  - Mine: from the user's own Outlook calendar (outlook.py's cached download,
    refreshed by the normal Outlook sync).
  - Partner: their published calendar link (Outlook, Google or iCloud .ics),
    downloaded here when the page opens (at most every 15 minutes) or on ↻.
"""

from datetime import date, datetime, timedelta
from urllib.parse import urlparse

import keyring

from venato import outlook
from venato import store

KEY_SERVICE, KEY_ACCOUNT = "Venato", "partner-ics-url"
MARK = "!"
REFRESH = timedelta(minutes=15)
CAL_HOSTS = outlook.OUTLOOK_HOSTS + ("calendar.google.com", "google.com", "icloud.com")

ME_COLOUR = "#F5C518"         # yellow
PARTNER_COLOUR = "#8E4EC6"    # purple


# ---------------------------------------------------------------------------
# The partner's link and name
# ---------------------------------------------------------------------------

def partner_url():
    try:
        return keyring.get_password(KEY_SERVICE, KEY_ACCOUNT) or None
    except Exception:
        return None


def partner_name():
    return store.load_settings().get("partner_name") or "Partner"


def check_link(text):
    """A pasted calendar link -> https URL. Raises outlook.LinkError with a reason."""
    url = (text or "").strip().strip("\"'<> ")
    if url.lower().startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    if not url:
        raise outlook.LinkError("Paste the calendar link first.")
    parts = urlparse(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https":
        raise outlook.LinkError("That doesn't look like a web link. It should start with https://")
    if not any(host == h or host.endswith("." + h) for h in CAL_HOSTS):
        raise outlook.LinkError("That isn't an Outlook, Google or iCloud calendar link.")
    if parts.path.lower().endswith(".html"):          # Outlook's web-view link: use the .ics one
        url = url.replace(parts.path, parts.path[:-5] + ".ics", 1)
    return url


def connect(url, name, fetcher=None):
    """Test the link, then save it (secret store) and the name, and import. Raises outlook.SyncError."""
    rows = rows_from((fetcher or outlook.fetch)(url))
    keyring.set_password(KEY_SERVICE, KEY_ACCOUNT, url)
    store.save_settings(partner_name=(name or "").strip() or "Partner",
                        partner_synced=datetime.now().isoformat(timespec="seconds"))
    store.replace_joint("partner", rows)
    return len(rows)


def disconnect():
    try:
        keyring.delete_password(KEY_SERVICE, KEY_ACCOUNT)
    except Exception:
        pass
    store.replace_joint("partner", [])
    store.save_settings(partner_synced=None)


# ---------------------------------------------------------------------------
# Reading a calendar, keeping only what the privacy rule allows
# ---------------------------------------------------------------------------

def shown_title(title):
    """The title to show, or None for an event that should be just blocked-out time."""
    if MARK not in (title or ""):
        return None
    return " ".join(title.replace(MARK, " ").split()) or None


def rows_from(ics_bytes, today=None):
    """
    joint_events rows (without `who`) from a calendar: timed events split at midnight
    into {uid, date, start_min, end_min, title, all_day}; all-day events one row per day.
    """
    rows = []
    for ev in outlook.parse(ics_bytes, today):
        title = shown_title(ev["title"])          # everything else about the event is dropped here
        if ev["all_day"]:
            day = ev["start"]
            while day < ev["end"]:
                rows.append({"uid": f"{ev['uid']}|{day}", "date": day.isoformat(), "start_min": None,
                             "end_min": None, "title": title, "all_day": 1})
                day += timedelta(days=1)
            continue
        s, e = ev["start"], ev["end"]
        day = s.date()
        while day <= e.date():
            day_start = datetime.combine(day, datetime.min.time(), s.tzinfo)
            a, b = max(s, day_start), min(e, day_start + timedelta(days=1))
            if a < b:
                rows.append({"uid": f"{ev['uid']}|{s.isoformat()}|{day}", "date": day.isoformat(),
                             "start_min": int((a - day_start).total_seconds() // 60),
                             "end_min": int((b - day_start).total_seconds() // 60),
                             "title": title, "all_day": 0})
            day += timedelta(days=1)
    return rows


# ---------------------------------------------------------------------------
# Refreshing
# ---------------------------------------------------------------------------

def refresh_mine(today=None):
    """Re-read the user's own Outlook calendar from its cached download."""
    if not outlook.ics_url() or not outlook.CACHE.exists():
        store.replace_joint("me", [])
        return False
    try:
        store.replace_joint("me", rows_from(outlook.CACHE.read_bytes(), today))
        return True
    except Exception:
        return False


def refresh_partner(force=False, fetcher=None, today=None):
    """Download the partner's calendar if it's been 15 minutes (or force). Returns an error message or None."""
    url = partner_url()
    if not url:
        return None
    last = store.load_settings().get("partner_synced")
    if not force and last and datetime.now() - datetime.fromisoformat(last) < REFRESH:
        return None
    try:
        rows = rows_from((fetcher or outlook.fetch)(url), today)
    except outlook.SyncError as e:
        return outlook.friendly(e).replace("Outlook", "the calendar")
    except Exception as e:
        return f"Couldn't read {partner_name()}'s calendar ({type(e).__name__})."
    store.replace_joint("partner", rows)
    store.save_settings(partner_synced=datetime.now().isoformat(timespec="seconds"))
    return None


def last_partner_sync():
    last = store.load_settings().get("partner_synced")
    return datetime.fromisoformat(last) if last else None


def week_of(day):
    first = day - timedelta(days=day.weekday())
    return [first + timedelta(days=i) for i in range(7)]


def events_for_week(first: date):
    last = first + timedelta(days=6)
    return store.joint_between(first.isoformat(), last.isoformat())
