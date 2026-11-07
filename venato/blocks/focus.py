"""
Focus: a Pomodoro timer (focus, then a short or long break) and a stopwatch for tracking
time on anything. Finished sessions are logged, and focus / tracked time of 15 minutes or
more can go straight into the Actual column of the timetable.

The running timer lives in the database (one row), not the browser, so it carries on
across reruns, page changes and restarts; the page just draws it (venato/ui/focus.py).
Times are stored as Unix seconds while running and as local "YYYY-MM-DDTHH:MM:SS" once
logged (in the user's time zone).
"""

import re
import threading
import time
import uuid
from datetime import datetime, timedelta

from venato import store
from venato.blocks import Block

KINDS = ("focus", "break", "track")
DEFAULTS = {"focus_minutes": 25, "short_break": 5, "long_break": 15, "long_every": 4,
            "auto_breaks": True, "to_timetable": True}
MIN_FOR_TIMETABLE = 15        # minutes: shorter sessions aren't put in the timetable

SCHEMA = """
CREATE TABLE IF NOT EXISTS focus_sessions (
    id           TEXT PRIMARY KEY,
    label        TEXT NOT NULL,
    category_id  TEXT,
    kind         TEXT NOT NULL,            -- focus / break / track
    started      TEXT NOT NULL,            -- local YYYY-MM-DDTHH:MM:SS
    ended        TEXT NOT NULL,
    minutes      REAL NOT NULL,
    planned      INTEGER,                  -- minutes, for timers
    completed    INTEGER NOT NULL DEFAULT 1,
    in_timetable INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS focus_running (
    one          INTEGER PRIMARY KEY CHECK (one = 1),
    label        TEXT NOT NULL,
    category_id  TEXT,
    kind         TEXT NOT NULL,
    started_at   REAL NOT NULL,            -- Unix seconds
    planned      INTEGER,                  -- minutes; NULL = stopwatch
    paused_at    REAL,
    paused_secs  REAL NOT NULL DEFAULT 0,
    cycle        INTEGER NOT NULL DEFAULT 0  -- focus sessions done in this run (for the long break)
);
"""


class FocusError(ValueError):
    pass


# --- Settings ---

def settings():
    saved = store.load_settings().get("focus") or {}
    return {**DEFAULTS, **{k: v for k, v in saved.items() if k in DEFAULTS}}


def save_settings(**changes):
    store.save_settings(focus={**settings(), **{k: v for k, v in changes.items() if k in DEFAULTS}})


# --- Time helpers ---

def _now():
    return time.time()


def _local(ts):
    return datetime.fromtimestamp(ts, store.tz()).replace(tzinfo=None)


def _iso(dt):
    return dt.isoformat(timespec="seconds")


# --- The running timer ---

COLS = ("label", "category_id", "kind", "started_at", "planned", "paused_at", "paused_secs", "cycle")


def running():
    with store.db() as conn:
        row = conn.execute(f"SELECT {', '.join(COLS)} FROM focus_running WHERE one = 1").fetchone()
    return dict(zip(COLS, row)) if row else None


def elapsed(r, now=None):
    """Seconds of the running session so far, not counting pauses."""
    now = now or _now()
    end = r["paused_at"] or now
    return max(0.0, end - r["started_at"] - r["paused_secs"])


def remaining(r, now=None):
    """Seconds left on a timer (None for the stopwatch)."""
    if r["planned"] is None:
        return None
    return r["planned"] * 60 - elapsed(r, now)


def start(label, minutes=None, kind="focus", category_id=None, cycle=None, now=None):
    """Start a timer (minutes) or the stopwatch (minutes=None, kind 'track'). Replaces nothing:
    stop the running one first."""
    if running():
        raise FocusError("A timer is already running: stop it first.")
    label = str(label or "").strip() or ("Break" if kind == "break" else "Focus")
    if kind not in KINDS:
        raise FocusError(f"kind must be one of {', '.join(KINDS)}.")
    if minutes is not None:
        minutes = int(minutes)
        if not 1 <= minutes <= 240:
            raise FocusError("A timer runs for 1 to 240 minutes.")
    with store.db() as conn:
        conn.execute(f"INSERT INTO focus_running ({', '.join(COLS)}, one) VALUES (?, ?, ?, ?, ?, NULL, 0, ?, 1)",
                     (label, category_id, kind, now or _now(), minutes, cycle or 0))
    return running()


def pause(now=None):
    r = running()
    if r and not r["paused_at"]:
        with store.db() as conn:
            conn.execute("UPDATE focus_running SET paused_at = ? WHERE one = 1", (now or _now(),))


def resume(now=None):
    r = running()
    if r and r["paused_at"]:
        with store.db() as conn:
            conn.execute("UPDATE focus_running SET paused_secs = paused_secs + ? - paused_at, paused_at = NULL "
                         "WHERE one = 1", (now or _now(),))


def cancel():
    """Throw the running session away (nothing logged)."""
    with store.db() as conn:
        conn.execute("DELETE FROM focus_running")


def stop(now=None, completed=None):
    """End the running session and log it. A timer that ran its full length counts as completed.
    Returns (session, note): note says what happened with the timetable."""
    r = running()
    if not r:
        return None, ""
    now = now or _now()
    secs = elapsed(r, now)
    if r["planned"] is not None:
        secs = min(secs, r["planned"] * 60)
        if completed is None:
            completed = secs >= r["planned"] * 60 - 1
    started = _local(r["started_at"])
    ended = started + timedelta(seconds=secs + r["paused_secs"]) if not r["paused_at"] else _local(r["paused_at"])
    cancel()
    session = _log(r["label"], r["kind"], started, ended, secs / 60, r["planned"], completed is not False,
                   r["category_id"])
    return session, _maybe_timetable(session)


_finishing = threading.Lock()     # the page and the reminder thread may both notice the same timer


def finish_if_due(now=None):
    """A timer that has run out: log it, and after a focus start the break (if breaks are on and
    it ran out just now, not while the app was closed). Returns a short message, or ''."""
    with _finishing:
        return _finish_if_due(now)


def _finish_if_due(now=None):
    r = running()
    if not r or r["planned"] is None or r["paused_at"]:
        return ""
    now = now or _now()
    left = remaining(r, now)
    if left > 0:
        return ""
    session, note = stop(now=r["started_at"] + r["paused_secs"] + r["planned"] * 60, completed=True)
    msg = f"{session['label']}: {session['minutes']:.0f} min done." + (f" {note}" if note else "")
    s = settings()
    if r["kind"] == "focus" and s["auto_breaks"] and -left < 90:
        cycle = r["cycle"] + 1
        long = cycle % max(1, int(s["long_every"])) == 0
        start("Long break" if long else "Break", s["long_break"] if long else s["short_break"], "break",
              cycle=cycle, now=now)
        msg += f" {'Long break' if long else 'Break'}: {s['long_break'] if long else s['short_break']} min."
    elif r["kind"] == "break":
        msg = "Break over: ready for the next focus?"
    return msg


# --- Logged sessions ---

SESSION_COLS = ("id", "label", "category_id", "kind", "started", "ended", "minutes", "planned", "completed",
                "in_timetable")


def _log(label, kind, started, ended, minutes, planned=None, completed=True, category_id=None):
    sid = uuid.uuid4().hex
    with store.db() as conn:
        conn.execute(f"INSERT INTO focus_sessions ({', '.join(SESSION_COLS)}, created_at) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
                     (sid, label, category_id, kind, _iso(started), _iso(ended), round(minutes, 2), planned,
                      int(bool(completed)), store.stamp()))
    return get(sid)


def get(sid):
    with store.db() as conn:
        row = conn.execute(f"SELECT {', '.join(SESSION_COLS)} FROM focus_sessions WHERE id = ?", (sid,)).fetchone()
    return dict(zip(SESSION_COLS, row)) if row else None


def sessions(first, last, kinds=("focus", "track")):
    """Sessions that started between two dates (inclusive), oldest first."""
    q = ",".join("?" * len(kinds))
    with store.db() as conn:
        rows = conn.execute(f"SELECT {', '.join(SESSION_COLS)} FROM focus_sessions WHERE kind IN ({q}) "
                            "AND substr(started, 1, 10) BETWEEN ? AND ? ORDER BY started",
                            (*kinds, str(first), str(last))).fetchall()
    return [dict(zip(SESSION_COLS, r)) for r in rows]


def delete(sid):
    with store.db() as conn:
        conn.execute("DELETE FROM focus_sessions WHERE id = ?", (sid,))


def log_manual(label, minutes, day=None, start_time=None, category_id=None):
    """Log time spent after the fact, e.g. 'I worked on the essay for 90 minutes this morning'."""
    minutes = float(minutes)
    if not 1 <= minutes <= 24 * 60:
        raise FocusError("Give between 1 minute and 24 hours.")
    day = store._as_date(day) if day else store.local_today()
    if start_time:
        h, m = map(int, str(start_time).split(":"))
        started = datetime(day.year, day.month, day.day, h, m)
    else:
        started = store.local_now() - timedelta(minutes=minutes) if day == store.local_today() else \
            datetime(day.year, day.month, day.day, 9, 0)
    session = _log(str(label).strip() or "Focus", "track", started, started + timedelta(minutes=minutes),
                   minutes, None, True, category_id)
    return session, _maybe_timetable(session)


def totals(first, last):
    """Minutes of focus + tracked time by label and by day, between two dates."""
    by_label, by_day = {}, {}
    for s in sessions(first, last):
        by_label[s["label"]] = by_label.get(s["label"], 0) + s["minutes"]
        day = s["started"][:10]
        by_day[day] = by_day.get(day, 0) + s["minutes"]
    return by_label, by_day


def streak(today=None):
    """Days in a row (to today, or yesterday if nothing yet today) with some focus time."""
    today = today or store.local_today()
    days = {s["started"][:10] for s in sessions(today - timedelta(days=400), today)}
    d = today if today.isoformat() in days else today - timedelta(days=1)
    n = 0
    while d.isoformat() in days:
        n += 1
        d -= timedelta(days=1)
    return n


# --- Into the timetable ---

def _half_hour(dt):
    """The nearest half-hour as minutes since midnight."""
    m = dt.hour * 60 + dt.minute + dt.second / 60
    return int(round(m / 30) * 30)


def _maybe_timetable(session):
    """Add a focus / tracked session of 15+ minutes to the Actual column, rounded to half hours,
    unless that would overwrite something there. Returns a note for the user."""
    if not settings()["to_timetable"] or session["kind"] == "break" or session["minutes"] < MIN_FOR_TIMETABLE:
        return ""
    from venato import tools
    started, ended = datetime.fromisoformat(session["started"]), datetime.fromisoformat(session["ended"])
    s, e = _half_hour(started), _half_hour(ended)
    if e <= s:
        e = s + 30
    hhmm = lambda m: f"{(m // 60) % 24:02d}:{m % 60:02d}"
    try:
        result = tools.add_block(started.date().isoformat(), "actual", hhmm(s), hhmm(e), session["label"],
                                 category=_category_name(session["category_id"]))
    except tools.ToolError:
        return "Not added to the timetable: pick a category for it (or give the activity a default category)."
    if result.pending:
        return "Not added to the timetable: something's already there at that time."
    with store.db() as conn:
        conn.execute("UPDATE focus_sessions SET in_timetable = 1 WHERE id = ?", (session["id"],))
    return f"Added to today's Actual, {hhmm(s)}–{hhmm(e)}."


def _category_name(cid):
    if not cid:
        return None
    cats = store.load_categories()
    names = dict(zip(cats["id"], cats["name"]))
    return names.get(cid)


# --- The assistant ---

def _status_text(now=None):
    r = running()
    if not r:
        return "No timer running."
    mins = elapsed(r, now) / 60
    what = f"{r['kind']} '{r['label']}'"
    if r["planned"] is None:
        state = f"stopwatch at {mins:.0f} min"
    else:
        state = f"{remaining(r, now) / 60:.0f} of {r['planned']} min left"
    return f"Running: {what}, {state}{' (paused)' if r['paused_at'] else ''}."


def tool_status():
    from venato import tools
    today = store.local_today()
    _, by_day = totals(today, today)
    return tools.Result(f"{_status_text()} Focus today: {by_day.get(today.isoformat(), 0):.0f} min.")


def tool_start(label="Focus", minutes=None, stopwatch=False, category=None):
    from venato import tools
    cid = store.resolve_category(label=label, category=category) if (category or label) else None
    try:
        if stopwatch:
            start(label, None, "track", cid)
        else:
            start(label, minutes or settings()["focus_minutes"], "focus", cid)
    except FocusError as e:
        raise tools.ToolError(str(e))
    return tools.Result(f"Started: {_status_text()}", changed=True)


def tool_stop(save=True):
    from venato import tools
    if not running():
        return tools.Result("No timer running.")
    if not save:
        cancel()
        return tools.Result("Timer cancelled; nothing logged.", changed=True)
    session, note = stop()
    return tools.Result(f"Stopped and logged {session['label']}: {session['minutes']:.0f} min. {note}".strip(),
                        changed=True)


def tool_log(label, minutes, date=None, start=None, category=None):
    from venato import tools
    cid = store.resolve_category(label=label, category=category)
    try:
        session, note = log_manual(label, minutes, date, start, cid)
    except (FocusError, ValueError) as e:
        raise tools.ToolError(str(e))
    return tools.Result(f"Logged {session['minutes']:.0f} min of {session['label']} on {session['started'][:10]}. "
                        f"{note}".strip(), changed=True)


def tool_summary(days=7):
    from venato import tools
    today = store.local_today()
    first = today - timedelta(days=max(1, min(int(days), 366)) - 1)
    by_label, by_day = totals(first, today)
    if not by_label:
        return tools.Result(f"No focus or tracked time in the last {days} days.")
    lines = [f"- {label}: {mins / 60:.1f} h" for label, mins in sorted(by_label.items(), key=lambda x: -x[1])]
    return tools.Result(f"Last {days} days: {sum(by_label.values()) / 60:.1f} h in total, streak {streak()} days.\n"
                        + "\n".join(lines))


def _context():
    today = store.local_today()
    _, by_day = totals(today, today)
    return f"{_status_text()} Focus / tracked today: {by_day.get(today.isoformat(), 0):.0f} min."


QUICK_START = re.compile(r"(?:start\s+(?:a\s+)?)?(?:focus|pomodoro)(?:\s+(?:for\s+)?(\d{1,3})\s*(?:m|min|mins|minutes)?)?"
                         r"(?:\s+(?:on|for)\s+(.+))?")


def _quick(text, day):
    """'focus', 'start focus 50 on essay', 'pomodoro on revision', 'stop focus', 'pause focus'."""
    from venato import tools
    if text in ("stop focus", "stop timer", "stop the timer", "end focus"):
        return tool_stop()
    if text in ("pause focus", "pause timer", "pause the timer"):
        if not running():
            return tools.Result("No timer running.")
        pause()
        return tools.Result("Paused.", changed=True)
    if text in ("resume focus", "resume timer", "resume the timer"):
        resume()
        return tools.Result("Resumed.", changed=True)
    m = QUICK_START.fullmatch(text)
    if not m or day != store.local_today():
        return None
    label = (m.group(2) or "Focus").strip().capitalize()
    return tool_start(label, int(m.group(1)) if m.group(1) else None)


PROMPT = """- Focus: a Pomodoro timer and a stopwatch for tracking time (the Focus page). focus_status says what's
  running and today's total. "start a 25 minute focus on the essay" -> start_focus(label="Essay", minutes=25);
  "track time on emails" -> start_focus(label="Emails", stopwatch=true); stop_focus ends and logs it
  (save=false throws it away). Time already spent: "I revised for 90 minutes this morning" ->
  log_focus(label="Revision", minutes=90, start=...). Sessions of 15+ minutes also go into the Actual
  timetable when there's room. focus_summary(days) totals time by activity."""


def _page():
    from venato.ui import focus as ui
    ui.render_page()


def _home():
    from venato.ui import focus as ui
    ui.render_home()


TOOLS = [
    ("focus_status", "What timer is running (if any) and today's focus total.",
     {"type": "object", "properties": {}, "required": []}, tool_status),
    ("start_focus", "Start a Pomodoro focus timer (minutes, default from Settings) or a stopwatch (stopwatch=true).",
     {"type": "object", "properties": {"label": {"type": "string"}, "minutes": {"type": "integer"},
                                       "stopwatch": {"type": "boolean"}, "category": {"type": "string"}},
      "required": []}, tool_start),
    ("stop_focus", "Stop the running timer and log it (save=false: throw it away).",
     {"type": "object", "properties": {"save": {"type": "boolean"}}, "required": []}, tool_stop),
    ("log_focus", "Log time already spent on something (minutes), optionally on a date (YYYY-MM-DD) and start (HH:mm).",
     {"type": "object", "properties": {"label": {"type": "string"}, "minutes": {"type": "number"},
                                       "date": {"type": "string"}, "start": {"type": "string"},
                                       "category": {"type": "string"}},
      "required": ["label", "minutes"]}, tool_log),
    ("focus_summary", "Focus and tracked time by activity over the last N days (default 7).",
     {"type": "object", "properties": {"days": {"type": "integer"}}, "required": []}, tool_summary),
]

BLOCK = Block("focus", "Focus", ":material/timer:",
              "A Pomodoro timer with breaks and a stopwatch for tracking time; sessions go into your timetable.",
              group="Plan", page=_page, home=_home, tools=TOOLS, prompt=PROMPT, context=_context,
              quick=[_quick], schema=SCHEMA, order=15)
