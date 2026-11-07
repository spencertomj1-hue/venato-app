"""
One-way import of the Outlook calendar into the timetable (read only: nothing
is ever written back to Outlook).

  fetch()   download the published .ics (its link is kept only in the macOS Keychain)
  parse()   expand recurring events (with their exceptions) in a window of 14 days back to
            8 weeks ahead, convert to the user's time zone, skip cancelled events
  to_rows() fit events to the timetable grid (its hours, 07:00-01:00 by default); after-midnight slots belong to the
            day before, start rounds down / end rounds up to 30 minutes
  sync()    all of the above, storing the rows in tt_outlook. The last good .ics is cached,
            so when offline the timetable keeps showing the cached events.

The URL is private: never log or display it. Error messages here never include it
(requests puts the URL in its exception text, so those are replaced).
"""

import math
from datetime import date, datetime, time, timedelta
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import icalendar
import keyring
import recurring_ical_events
import requests
from icalendar.timezone.windows_to_olson import WINDOWS_TO_OLSON

from venato import store
from venato import system

CACHE = store.DATA_DIR / ".outlook_cache.ics"   # last good download (gitignored)
KEYCHAIN_SERVICE = "Venato"                 # the link is stored in the macOS Keychain
KEYCHAIN_ACCOUNT = "outlook-ics-url"
OUTLOOK_HOSTS = ("outlook.office365.com", "outlook.office.com", "outlook.live.com", "outlook.com")

DAYS_BACK = 14
WEEKS_AHEAD = 8
TIMEOUT = 10                               # seconds
SLOT = timedelta(minutes=30)


class SyncError(Exception):
    """Couldn't get the calendar. The message is safe to show (it never contains the URL).
    kind: "timeout", "offline", "http" (see .status), "notcal" or "error"."""

    def __init__(self, message, kind="error", status=None):
        super().__init__(message)
        self.kind, self.status = kind, status


class LinkError(Exception):
    """A pasted calendar link that isn't usable (the message says why)."""


# ---------------------------------------------------------------------------
# Where the link is kept: only in the macOS Keychain
# ---------------------------------------------------------------------------

def ics_url():
    """The calendar URL, or None if no calendar is connected."""
    try:
        url = keyring.get_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)
        if not url:                                   # saved before the rename: copy it to the new name
            url = keyring.get_password(system.OLD_NAME, KEYCHAIN_ACCOUNT)
            if url:
                keyring.set_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT, url)
        return url or None
    except Exception:
        return None


def save_url(url):
    keyring.set_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT, url)


def disconnect():
    """Forget the link (Keychain) and the imported events."""
    for service in (KEYCHAIN_SERVICE, system.OLD_NAME):   # the old name's copy too
        try:
            keyring.delete_password(service, KEYCHAIN_ACCOUNT)
        except Exception:
            pass
    CACHE.unlink(missing_ok=True)
    if extra_calendars():
        sync()
    else:
        store.replace_outlook([])


# ---------------------------------------------------------------------------
# Connecting: check a pasted link, then try it
# ---------------------------------------------------------------------------

def check_link(text):
    """
    Validate a pasted link: https, an Outlook domain, ending in .ics. A pasted
    .html link (the web view) is swapped for the .ics one. Returns (url, note).
    """
    url = (text or "").strip().strip("\"'<> ")
    if not url:
        raise LinkError("Paste the ICS link from Outlook first.")
    parts = urlparse(url)
    if parts.scheme != "https":
        raise LinkError("That doesn't look like a web link. It should start with https://outlook.office365.com/…")
    host = (parts.hostname or "").lower()
    if not any(host == h or host.endswith("." + h) for h in OUTLOOK_HOSTS):
        raise LinkError("That isn't an Outlook calendar link. It should start with https://outlook.office365.com/… "
                        "(or outlook.office.com / outlook.live.com).")
    note = None
    if parts.path.lower().endswith(".html"):
        parts = parts._replace(path=parts.path[:-5] + ".ics")
        url = urlunparse(parts)
        note = "You pasted the HTML link (for viewing in a browser), so Venato switched it to the ICS link."
    if not parts.path.lower().endswith(".ics"):
        raise LinkError("The link should end in .ics. In Outlook, copy the ICS link, not the HTML one.")
    return url, note


def friendly(error):
    """A plain-English explanation of a failed test fetch."""
    if error.kind in ("offline", "timeout"):
        return "Couldn't reach Outlook. Check you're connected to the internet, then try again."
    if error.kind == "http" and error.status in (401, 403):
        return ("Outlook refused this link. Some university and work accounts don't allow publishing "
                "calendars; if Outlook didn't offer \"Publish a calendar\", ask your IT team. If you reset or "
                "unpublished the link, publish again and paste the new ICS link.")
    if error.kind == "http" and error.status == 404:
        return ("Outlook couldn't find that calendar. The link may have been reset or unpublished. "
                "Publish it again in Outlook and paste the new ICS link.")
    if error.kind == "notcal":
        return "That link didn't return a calendar. Make sure you copied the ICS link (ending in .ics)."
    return str(error)


def try_link(url, fetcher=None, today=None):
    """
    Test-download a calendar link. Returns {data, count, preview}: the number of
    events in the next 2 weeks and the next 3 of them. Raises SyncError.
    """
    data = (fetcher or fetch)(url)
    now = datetime.now(store.tz())
    soon = []
    for ev in parse(data, today):
        start = ev["start"] if not ev["all_day"] else datetime.combine(ev["start"], time(0), store.tz())
        if now - timedelta(hours=1) <= start <= now + timedelta(days=14):
            soon.append((start, ev))
    soon.sort(key=lambda p: p[0])
    preview = [{"title": ev["title"],
                "when": f"{s:%a} {s.day} {s:%b}, " + ("all day" if ev["all_day"] else f"{s:%H:%M}")}
               for s, ev in soon[:3]]
    return {"data": data, "count": len(soon), "preview": preview}


def connect(url, data):
    """Save a working link to the Keychain and import its events."""
    save_url(url)
    return sync(fetcher=lambda _: data)


def fetch(url):
    """Download the .ics. Raises SyncError (without the URL in it) on any failure."""
    try:
        response = requests.get(url, timeout=TIMEOUT)
        response.raise_for_status()
    except requests.Timeout:
        raise SyncError("Outlook didn't respond in time.", "timeout") from None
    except requests.ConnectionError:
        raise SyncError("Couldn't reach Outlook (offline?).", "offline") from None
    except requests.HTTPError:
        status = response.status_code
        raise SyncError(f"Outlook refused the request (HTTP {status}).", "http", status) from None
    except requests.RequestException as e:
        raise SyncError(f"Couldn't download the calendar ({type(e).__name__}).") from None
    if not response.content.lstrip().startswith(b"BEGIN:VCALENDAR"):
        raise SyncError("The calendar link didn't return a calendar.", "notcal")
    return response.content


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _to_london(value, tzid=None):
    """Aware datetime in the user's time zone (store.tz()). Naive times use their TZID (Windows names mapped)."""
    if value.tzinfo is None:
        try:
            zone = ZoneInfo(WINDOWS_TO_OLSON.get(tzid, tzid)) if tzid else store.tz()
        except (ZoneInfoNotFoundError, ValueError):
            zone = store.tz()
        value = value.replace(tzinfo=zone)
    return value.astimezone(store.tz())


def parse(ics_bytes, today=None):
    """Events in the sync window, as dicts: uid, title, location, all_day, start, end."""
    today = today or store.local_today()
    window = (today - timedelta(days=DAYS_BACK), today + timedelta(weeks=WEEKS_AHEAD))
    calendar = icalendar.Calendar.from_ical(ics_bytes)

    events = []
    for ev in recurring_ical_events.of(calendar).between(*window):
        # Skip cancelled events. Outlook usually doesn't set STATUS:CANCELLED on meetings
        # someone else cancelled: it keeps them CONFIRMED with a "Canceled: ..." title.
        title = str(ev.get("SUMMARY", "")).strip()
        if str(ev.get("STATUS", "")).upper() == "CANCELLED" or title.lower().startswith(("canceled:", "cancelled:")):
            continue
        start = ev.decoded("DTSTART")
        if "DTEND" in ev:
            end = ev.decoded("DTEND")
        elif "DURATION" in ev:
            end = start + ev.decoded("DURATION")
        else:
            end = start + (timedelta(days=1) if not isinstance(start, datetime) else timedelta(0))
        info = {
            "uid": str(ev.get("UID", "")),
            "title": title or "(No title)",
            "location": str(ev.get("LOCATION", "")).strip().strip("-–— ") or None,   # "-" means none
            "description": short_description(str(ev.get("DESCRIPTION", ""))),
        }
        if isinstance(start, datetime):
            tzid = ev["DTSTART"].params.get("TZID")
            events.append({**info, "all_day": False, "start": _to_london(start, tzid), "end": _to_london(end, tzid)})
        else:
            events.append({**info, "all_day": True, "start": start, "end": end})   # dates; end exclusive
    return events


def short_description(text, limit=300):
    """The event's notes, without the Teams/Zoom join boilerplate, cut to a short snippet."""
    lines = []
    for line in text.replace("\r", "").split("\n"):
        line = line.strip()
        low = line.lower()
        if not line or set(line) <= set("_-=*~ "):
            continue
        if low.startswith(("microsoft teams", "join the meeting", "join on your computer", "meeting id",
                           "passcode", "need help?", "for organizers", "join:", "https://teams.", "<https://")):
            break                                    # the rest is the dial-in block
        lines.append(line)
    snippet = " ".join(lines)
    return (snippet[:limit - 1].rstrip() + "…" if len(snippet) > limit else snippet) or None


def _grid_rows(ev):
    """Pieces of a timed event that fall on timetable days, snapped to 30-minute slots."""
    s, e = ev["start"], ev["end"]
    exact = f"{s:%H:%M}–{e:%H:%M}" if s.date() == e.date() else f"{s:%a %H:%M} – {e:%a %H:%M}"
    rows = []
    day = s.date() - timedelta(days=1)          # an event at 00:30 belongs to the day before
    while day <= e.date():
        g0 = datetime.combine(day, time(store.FIRST_MIN // 60), store.tz())      # the timetable day's hours
        g1 = g0 + timedelta(minutes=30 * store.SLOTS)
        a, b = max(s, g0), min(e, g1)            # clip to the grid
        if a < b:
            first = math.floor((a - g0) / SLOT)   # start rounds down
            last = math.ceil((b - g0) / SLOT)     # end rounds up
            rows.append({
                "uid": f"{ev['uid']}|{s.isoformat()}|{day}", "date": day.isoformat(),
                "start": store.slot_time(first), "end": store.slot_time(min(last, store.SLOTS)),
                "title": ev["title"], "location": ev["location"], "all_day": 0, "exact": exact,
                "description": ev.get("description"),
            })
        day += timedelta(days=1)
    return rows


def to_rows(events):
    """tt_outlook rows for parsed events (all-day events get one row per day)."""
    rows = []
    for ev in events:
        if not ev["all_day"]:
            rows += _grid_rows(ev)
            continue
        day = ev["start"]
        while day < ev["end"]:
            rows.append({"uid": f"{ev['uid']}|{day}", "date": day.isoformat(), "start": None, "end": None,
                         "title": ev["title"], "location": ev["location"], "all_day": 1, "exact": None,
                         "description": ev.get("description")})
            day += timedelta(days=1)
    return rows


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------

def last_synced():
    """When the cached calendar was last downloaded, or None."""
    return datetime.fromtimestamp(CACHE.stat().st_mtime) if CACHE.exists() else None


def _rows_for(url, cache, today, fetcher, prefix=""):
    """(rows, error) for one calendar; falls back to its cached copy when the download fails."""
    error = None
    try:
        data = fetcher(url)
        rows = to_rows(parse(data, today))     # check it parses before replacing the cache
        cache.write_bytes(data)
    except SyncError as e:
        error, rows = str(e), None
    except Exception as e:                     # a malformed calendar
        error, rows = f"Couldn't read the calendar ({type(e).__name__}).", None
    if rows is None and cache.exists():
        try:
            rows = to_rows(parse(cache.read_bytes(), today))   # re-parse so the window moves on
        except Exception:
            rows = None
    if rows is not None and prefix:
        rows = [{**r, "uid": prefix + r["uid"]} for r in rows]
    return rows, error


def sync(today=None, fetcher=fetch):
    """
    Download, parse and store the calendars (Outlook and any others added). If a download
    fails, that calendar's cached copy is used so the timetable keeps showing its events.
    Returns a status dict: {ok, error, synced_at, count}.
    """
    url = ics_url()
    others = extra_calendars()
    if not url and not others:
        return {"ok": False, "error": "No calendar is set up.", "synced_at": None, "count": 0}
    errors, rows, any_rows = [], [], False
    jobs = ([(url, CACHE, "", "Outlook")] if url else []) + \
           [(c["url"], _extra_cache(c["id"]), f"cal{c['id']}|", c["name"]) for c in others]
    for u, cache, prefix, name in jobs:
        got, error = _rows_for(u, cache, today, fetcher, prefix)
        if error:
            errors.append(f"{name}: {error}" if len(jobs) > 1 else error)
        if got is not None:
            rows += got
            any_rows = True
    if any_rows:
        store.replace_outlook(rows)
    return {"ok": not errors, "error": "; ".join(errors) or None, "synced_at": last_synced(), "count": len(rows)}


# ---------------------------------------------------------------------------
# Other calendars (Google, iCloud, any published .ics): their links are in the Keychain too
# ---------------------------------------------------------------------------

EXTRA_ACCOUNT = "extra-calendars"
MAX_EXTRA = 10


def _extra_cache(cid):
    return store.DATA_DIR / f".calendar_{cid}.ics"


def extra_calendars():
    """[{id, name, url}] of the other calendars (the links come from the Keychain)."""
    import json
    try:
        raw = keyring.get_password(KEYCHAIN_SERVICE, EXTRA_ACCOUNT)
        items = json.loads(raw) if raw else []
        return [c for c in items if isinstance(c, dict) and {"id", "name", "url"} <= set(c)]
    except Exception:
        return []


def _save_extra(items):
    import json
    if items:
        keyring.set_password(KEYCHAIN_SERVICE, EXTRA_ACCOUNT, json.dumps(items))
    else:
        try:
            keyring.delete_password(KEYCHAIN_SERVICE, EXTRA_ACCOUNT)
        except Exception:
            pass


def check_any_link(text):
    """A secret / public calendar link from Google, iCloud or anywhere: https (webcal:// is
    turned into https://), and not a local or private address. Returns (url, provider)."""
    import ipaddress
    url = (text or "").strip().strip("\"'<> ")
    if url.lower().startswith("webcal://"):
        url = "https://" + url[9:]
    parts = urlparse(url)
    if parts.scheme != "https" or not parts.hostname:
        raise LinkError("Paste the calendar's link: it starts with https:// (or webcal://).")
    host = parts.hostname.lower()
    try:
        ip = ipaddress.ip_address(host)
        if not ip.is_global:
            raise LinkError("That's a local network address, not a calendar on the internet.")
    except ValueError:
        if host == "localhost" or host.endswith((".local", ".localhost", ".internal")):
            raise LinkError("That's a local network address, not a calendar on the internet.")
    provider = ("Google" if host == "calendar.google.com" else "iCloud" if host.endswith("icloud.com")
                else "Outlook" if any(host == h or host.endswith("." + h) for h in OUTLOOK_HOSTS) else "Other")
    if provider == "Google" and "/ical/" not in parts.path:
        raise LinkError("Use the \"Secret address in iCal format\" from Google Calendar's settings (it ends in basic.ics).")
    return url, provider


def add_calendar(name, url, data):
    """Save another calendar (after try_link worked) and sync everything."""
    import uuid
    items = extra_calendars()
    if len(items) >= MAX_EXTRA:
        raise LinkError(f"You can add up to {MAX_EXTRA} calendars.")
    if any(c["url"] == url for c in items) or url == ics_url():
        raise LinkError("That calendar is already added.")
    cid = uuid.uuid4().hex[:10]
    _save_extra(items + [{"id": cid, "name": str(name or "Calendar").strip()[:40] or "Calendar", "url": url}])
    _extra_cache(cid).write_bytes(data)
    return sync(fetcher=lambda u: data if u == url else fetch(u))


def remove_calendar(cid):
    _save_extra([c for c in extra_calendars() if c["id"] != cid])
    _extra_cache(cid).unlink(missing_ok=True)
    if ics_url() or extra_calendars():
        sync()
    else:
        store.replace_outlook([])


def ago(when, now=None):
    """'just now', '5 min ago', '3 h ago', '2 days ago'."""
    if when is None:
        return "never"
    minutes = int(((now or datetime.now()) - when).total_seconds() // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} min ago"
    if minutes < 48 * 60:
        return f"{minutes // 60} h ago"
    return f"{minutes // (24 * 60)} days ago"
