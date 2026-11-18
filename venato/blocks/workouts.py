"""
Workouts: an exercise library, workouts made of sets (weights / reps, distance, time,
warm-ups, RPE), saved plans to start from, personal bests and estimated one-rep maxes,
progress per exercise and weekly volume per muscle group.

Weights are stored in kg and distances in km; Settings → Workouts chooses lb / miles for
showing and typing them.
"""

import re
import uuid
from datetime import timedelta

from venato import store
from venato.blocks import Block

KINDS = ("weights", "bodyweight", "cardio", "timed")
MUSCLES = ("Chest", "Back", "Shoulders", "Biceps", "Triceps", "Forearms", "Core", "Quads", "Hamstrings",
           "Glutes", "Calves", "Full body", "Cardio")
LB = 0.45359237
MILE = 1.609344

STARTER = [     # (name, kind, muscle)
    ("Bench press", "weights", "Chest"), ("Incline dumbbell press", "weights", "Chest"),
    ("Push-up", "bodyweight", "Chest"), ("Chest fly", "weights", "Chest"), ("Dips", "bodyweight", "Triceps"),
    ("Deadlift", "weights", "Back"), ("Barbell row", "weights", "Back"), ("Pull-up", "bodyweight", "Back"),
    ("Lat pulldown", "weights", "Back"), ("Seated cable row", "weights", "Back"),
    ("Overhead press", "weights", "Shoulders"), ("Lateral raise", "weights", "Shoulders"),
    ("Face pull", "weights", "Shoulders"), ("Bicep curl", "weights", "Biceps"), ("Hammer curl", "weights", "Biceps"),
    ("Tricep pushdown", "weights", "Triceps"), ("Skull crusher", "weights", "Triceps"),
    ("Squat", "weights", "Quads"), ("Front squat", "weights", "Quads"), ("Leg press", "weights", "Quads"),
    ("Lunge", "weights", "Quads"), ("Leg extension", "weights", "Quads"),
    ("Romanian deadlift", "weights", "Hamstrings"), ("Leg curl", "weights", "Hamstrings"),
    ("Hip thrust", "weights", "Glutes"), ("Calf raise", "weights", "Calves"),
    ("Plank", "timed", "Core"), ("Crunch", "bodyweight", "Core"), ("Hanging leg raise", "bodyweight", "Core"),
    ("Running", "cardio", "Cardio"), ("Cycling", "cardio", "Cardio"), ("Rowing", "cardio", "Cardio"),
    ("Swimming", "cardio", "Cardio"), ("Walking", "cardio", "Cardio"), ("Elliptical", "cardio", "Cardio"),
    ("Burpee", "bodyweight", "Full body"), ("Kettlebell swing", "weights", "Full body"),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS wk_exercises (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    kind       TEXT NOT NULL,              -- weights / bodyweight / cardio / timed
    muscle     TEXT,
    notes      TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS wk_workouts (
    id         TEXT PRIMARY KEY,
    date       TEXT NOT NULL,              -- YYYY-MM-DD
    start      TEXT,                       -- HH:mm
    title      TEXT NOT NULL,
    notes      TEXT,
    minutes    REAL,                       -- how long it took
    rpe        REAL,                       -- how hard, 1-10
    source     TEXT NOT NULL DEFAULT 'manual',   -- manual / strava / whoop / apple health / google fit
    source_id  TEXT,                       -- the id in that source, so imports don't repeat
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS wk_sets (
    id          TEXT PRIMARY KEY,
    workout_id  TEXT NOT NULL REFERENCES wk_workouts(id) ON DELETE CASCADE,
    exercise_id TEXT NOT NULL REFERENCES wk_exercises(id),
    ord         INTEGER NOT NULL,
    reps        INTEGER,
    weight      REAL,                      -- kg
    distance    REAL,                      -- km
    seconds     INTEGER,
    warmup      INTEGER NOT NULL DEFAULT 0,
    rpe         REAL
);
CREATE TABLE IF NOT EXISTS wk_plans (
    id    TEXT PRIMARY KEY,
    name  TEXT NOT NULL UNIQUE COLLATE NOCASE,
    notes TEXT
);
CREATE TABLE IF NOT EXISTS wk_plan_items (
    plan_id     TEXT NOT NULL REFERENCES wk_plans(id) ON DELETE CASCADE,
    ord         INTEGER NOT NULL,
    exercise_id TEXT NOT NULL REFERENCES wk_exercises(id),
    sets        INTEGER NOT NULL,
    reps        INTEGER,
    weight      REAL
);
CREATE INDEX IF NOT EXISTS wk_workouts_date ON wk_workouts(date);
CREATE INDEX IF NOT EXISTS wk_sets_workout ON wk_sets(workout_id);
"""


class WorkoutError(ValueError):
    pass


def _id():
    return uuid.uuid4().hex


# --- Units ---

def units():
    s = store.load_settings().get("workouts") or {}
    return s.get("weight", "kg"), s.get("distance", "km")


def save_units(weight=None, distance=None):
    w, d = units()
    store.save_settings(workouts={**(store.load_settings().get("workouts") or {}),
                                  "weight": weight or w, "distance": distance or d})


def kg_in(value):
    """The user's weight unit -> kg."""
    return None if value in (None, "") else float(value) * (LB if units()[0] == "lb" else 1)


def kg_out(kg):
    return None if kg is None else round(kg / (LB if units()[0] == "lb" else 1), 1)


def km_in(value):
    return None if value in (None, "") else float(value) * (MILE if units()[1] == "mi" else 1)


def km_out(km):
    return None if km is None else round(km / (MILE if units()[1] == "mi" else 1), 2)


def weight_text(kg):
    return "" if kg is None else f"{kg_out(kg):g} {units()[0]}"


# --- Exercises ---

EX_COLS = ("id", "name", "kind", "muscle", "notes")


def _seed(conn):
    if conn.execute("SELECT COUNT(*) FROM wk_exercises").fetchone()[0] == 0:
        conn.executemany("INSERT INTO wk_exercises (id, name, kind, muscle, created_at) VALUES (?, ?, ?, ?, ?)",
                         [(_id(), n, k, m, store.stamp()) for n, k, m in STARTER])


def exercises():
    with store.db() as conn:
        _seed(conn)
        rows = conn.execute(f"SELECT {', '.join(EX_COLS)} FROM wk_exercises ORDER BY name COLLATE NOCASE").fetchall()
    return [dict(zip(EX_COLS, r)) for r in rows]


def find_exercise(name):
    """An exercise by name (any case), or by a close match ('bench' -> 'Bench press'), or None."""
    want = str(name or "").strip().lower()
    if not want:
        return None
    pool = exercises()
    exact = [e for e in pool if e["name"].lower() == want or e["name"].lower().rstrip("s") == want.rstrip("s")]
    if exact:
        return exact[0]
    part = [e for e in pool if e["name"].lower().startswith(want)] or [e for e in pool if want in e["name"].lower()]
    return part[0] if len(part) == 1 else None


def add_exercise(name, kind="weights", muscle=None, notes=None):
    name = str(name or "").strip()
    if not name:
        raise WorkoutError("The exercise needs a name.")
    if kind not in KINDS:
        raise WorkoutError(f"kind must be one of {', '.join(KINDS)}.")
    found = [e for e in exercises() if e["name"].lower() == name.lower()]
    if found:
        return found[0]
    eid = _id()
    with store.db() as conn:
        conn.execute("INSERT INTO wk_exercises (id, name, kind, muscle, notes, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                     (eid, name, kind, muscle, notes, store.stamp()))
    return next(e for e in exercises() if e["id"] == eid)


def exercise_or_new(name, kind=None):
    return find_exercise(name) or add_exercise(name, kind or "weights")


# --- Workouts and sets ---

WK_COLS = ("id", "date", "start", "title", "notes", "minutes", "rpe", "source", "source_id")
SET_COLS = ("id", "workout_id", "exercise_id", "ord", "reps", "weight", "distance", "seconds", "warmup", "rpe")


def add_workout(date=None, title="Workout", start=None, notes=None, minutes=None, rpe=None, source="manual",
                source_id=None):
    day = store._as_date(date) if date else store.local_today()
    if source_id:
        with store.db() as conn:
            row = conn.execute("SELECT id FROM wk_workouts WHERE source = ? AND source_id = ?",
                               (source, source_id)).fetchone()
        if row:
            return row[0]                       # already imported
    wid = _id()
    with store.db() as conn:
        conn.execute(f"INSERT INTO wk_workouts ({', '.join(WK_COLS)}, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (wid, day.isoformat(), start, str(title or "Workout").strip() or "Workout", notes, minutes, rpe,
                      source, source_id, store.stamp()))
    _tick_habit(day)
    return wid


def update_workout(wid, **fields):
    allowed = {k: v for k, v in fields.items() if k in ("date", "start", "title", "notes", "minutes", "rpe")}
    if allowed:
        with store.db() as conn:
            conn.execute(f"UPDATE wk_workouts SET {', '.join(f'{k} = ?' for k in allowed)} WHERE id = ?",
                         (*allowed.values(), wid))


def get_workout(wid):
    with store.db() as conn:
        row = conn.execute(f"SELECT {', '.join(WK_COLS)} FROM wk_workouts WHERE id = ?", (wid,)).fetchone()
    return dict(zip(WK_COLS, row)) if row else None


def workouts(first, last):
    with store.db() as conn:
        rows = conn.execute(f"SELECT {', '.join(WK_COLS)} FROM wk_workouts WHERE date BETWEEN ? AND ? "
                            "ORDER BY date DESC, start DESC, created_at DESC", (str(first), str(last))).fetchall()
    return [dict(zip(WK_COLS, r)) for r in rows]


def workout_on(day, create_title=None):
    """Today's (or a day's) latest manual workout; with create_title, make one if there's none."""
    with store.db() as conn:
        row = conn.execute("SELECT id FROM wk_workouts WHERE date = ? AND source = 'manual' "
                           "ORDER BY created_at DESC LIMIT 1", (str(day),)).fetchone()
    if row:
        return row[0]
    return add_workout(day, create_title) if create_title else None


def delete_workout(wid):
    with store.db() as conn:
        conn.execute("DELETE FROM wk_sets WHERE workout_id = ?", (wid,))
        conn.execute("DELETE FROM wk_workouts WHERE id = ?", (wid,))


def add_sets(wid, exercise_id, count=1, reps=None, weight=None, distance=None, seconds=None, warmup=False, rpe=None):
    """Add `count` identical sets of an exercise (weight in kg, distance in km)."""
    count = 1 if count is None else int(count)
    if not 1 <= count <= 50:
        raise WorkoutError("Add 1 to 50 sets at a time.")
    for name, v, hi in (("reps", reps, 1000), ("weight", weight, 2000), ("distance", distance, 1000),
                        ("seconds", seconds, 86400), ("rpe", rpe, 10)):
        if v is not None and not 0 <= float(v) <= hi:
            raise WorkoutError(f"{name} looks wrong ({v}).")
    with store.db() as conn:
        start = conn.execute("SELECT COALESCE(MAX(ord), -1) + 1 FROM wk_sets WHERE workout_id = ?", (wid,)).fetchone()[0]
        conn.executemany(f"INSERT INTO wk_sets ({', '.join(SET_COLS)}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         [(_id(), wid, exercise_id, start + i, None if reps is None else int(reps), weight, distance,
                           None if seconds is None else int(seconds), int(bool(warmup)), rpe) for i in range(count)])


def sets_of(wid):
    """The sets of a workout, in order, with their exercise's name, kind and muscle."""
    with store.db() as conn:
        rows = conn.execute(f"SELECT {', '.join('s.' + c for c in SET_COLS)}, e.name, e.kind, e.muscle "
                            "FROM wk_sets s JOIN wk_exercises e ON e.id = s.exercise_id "
                            "WHERE s.workout_id = ? ORDER BY s.ord", (wid,)).fetchall()
    return [dict(zip(SET_COLS + ("exercise", "kind", "muscle"), r)) for r in rows]


def update_set(sid, **fields):
    allowed = {k: v for k, v in fields.items() if k in ("reps", "weight", "distance", "seconds", "warmup", "rpe")}
    if allowed:
        with store.db() as conn:
            conn.execute(f"UPDATE wk_sets SET {', '.join(f'{k} = ?' for k in allowed)} WHERE id = ?",
                         (*allowed.values(), sid))


def delete_set(sid):
    with store.db() as conn:
        conn.execute("DELETE FROM wk_sets WHERE id = ?", (sid,))


def all_sets(first=None, last=None):
    """Every set (with its date, exercise and muscle), optionally between two dates."""
    where, params = "", ()
    if first:
        where, params = "WHERE w.date BETWEEN ? AND ?", (str(first), str(last))
    with store.db() as conn:
        rows = conn.execute(f"SELECT w.date, w.id, {', '.join('s.' + c for c in SET_COLS[2:])}, e.name, e.kind, e.muscle "
                            "FROM wk_sets s JOIN wk_workouts w ON w.id = s.workout_id "
                            f"JOIN wk_exercises e ON e.id = s.exercise_id {where} ORDER BY w.date, s.ord",
                            params).fetchall()
    keys = ("date", "workout_id") + SET_COLS[2:] + ("exercise", "kind", "muscle")
    return [dict(zip(keys, r)) for r in rows]


# --- Plans (templates) ---

def plans():
    with store.db() as conn:
        rows = conn.execute("SELECT id, name, notes FROM wk_plans ORDER BY name COLLATE NOCASE").fetchall()
    return [dict(zip(("id", "name", "notes"), r)) for r in rows]


def plan_items(pid):
    with store.db() as conn:
        rows = conn.execute("SELECT i.exercise_id, e.name, i.sets, i.reps, i.weight FROM wk_plan_items i "
                            "JOIN wk_exercises e ON e.id = i.exercise_id WHERE i.plan_id = ? ORDER BY i.ord",
                            (pid,)).fetchall()
    return [dict(zip(("exercise_id", "exercise", "sets", "reps", "weight"), r)) for r in rows]


def save_plan_from(wid, name):
    """Save a workout's exercises (sets, reps and weight of its working sets) as a plan."""
    name = str(name or "").strip()
    if not name:
        raise WorkoutError("The plan needs a name.")
    groups = {}
    for s in sets_of(wid):
        if s["warmup"]:
            continue
        g = groups.setdefault(s["exercise_id"], {"sets": 0, "reps": s["reps"], "weight": s["weight"]})
        g["sets"] += 1
    if not groups:
        raise WorkoutError("That workout has no working sets to save.")
    with store.db() as conn:
        old = conn.execute("SELECT id FROM wk_plans WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
        if old:
            conn.execute("DELETE FROM wk_plan_items WHERE plan_id = ?", (old[0],))
            pid = old[0]
        else:
            pid = _id()
            conn.execute("INSERT INTO wk_plans (id, name) VALUES (?, ?)", (pid, name))
        conn.executemany("INSERT INTO wk_plan_items VALUES (?, ?, ?, ?, ?, ?)",
                         [(pid, i, eid, g["sets"], g["reps"], g["weight"]) for i, (eid, g) in enumerate(groups.items())])
    return pid


def start_from_plan(pid, day=None):
    p = next((x for x in plans() if x["id"] == pid), None)
    if not p:
        raise WorkoutError("No such plan.")
    wid = add_workout(day, p["name"])
    for item in plan_items(pid):
        add_sets(wid, item["exercise_id"], item["sets"], item["reps"], item["weight"])
    return wid


def delete_plan(pid):
    with store.db() as conn:
        conn.execute("DELETE FROM wk_plan_items WHERE plan_id = ?", (pid,))
        conn.execute("DELETE FROM wk_plans WHERE id = ?", (pid,))


def save_plan(name, items, notes=None):
    """Save (or replace) a plan from [{exercise, sets, reps, weight (kg)}]; unknown exercises are added."""
    name = str(name or "").strip()
    if not name:
        raise WorkoutError("The plan needs a name.")
    if not items:
        raise WorkoutError(f"The plan {name} has no exercises.")
    rows = [(exercise_or_new(it["exercise"], it.get("kind"))["id"], max(1, int(it.get("sets") or 1)),
             it.get("reps"), it.get("weight")) for it in items]
    with store.db() as conn:
        old = conn.execute("SELECT id FROM wk_plans WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
        if old:
            pid = old[0]
            conn.execute("DELETE FROM wk_plan_items WHERE plan_id = ?", (pid,))
            conn.execute("UPDATE wk_plans SET notes = ? WHERE id = ?", (notes, pid))
        else:
            pid = _id()
            conn.execute("INSERT INTO wk_plans (id, name, notes) VALUES (?, ?, ?)", (pid, name, notes))
        conn.executemany("INSERT INTO wk_plan_items VALUES (?, ?, ?, ?, ?, ?)",
                         [(pid, i, *r) for i, r in enumerate(rows)])
    return pid


# --- Uploading a plan (text or CSV) and fitting it into the timetable ---

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_NUM = r"\d+(?:\.\d+)?"
_WEIGHT = rf"(?:\s*(?:@|at)\s*(?P<w>{_NUM})\s*(?P<wu>kgs?|lbs?)?|\s+(?P<w2>{_NUM})\s*(?P<wu2>kgs?|lbs?)?)"
_SETS = (r"(?P<sets>\d{1,2})\s*(?:[x×]|sets?\s*(?:of|x)?)\s*(?P<reps>\d{1,3})(?:\s*[-–]\s*\d{1,3})?"
         r"(?P<secs>\s*(?:s|secs?|seconds)\b)?(?:\s*reps?\b)?")
_ITEM = re.compile(rf"(?P<name>[^\d].*?)\s*[:\-–,]?\s*{_SETS}{_WEIGHT}?\s*(?:\((?P<note>[^)]*)\))?\.?", re.I)
_CARDIO = re.compile(rf"(?P<name>[^\d].*?)\s*[:\-–,]?\s*(?:for\s+)?(?P<num>{_NUM})\s*"
                     r"(?P<unit>km|k|kms|mi|miles?|mins?|minutes?|hrs?|hours?)\b.*", re.I)
_BULLET = re.compile(r"^\s*(?:[-*•·]|\d{1,2}[.)])\s+")


def _weekday(text):
    """'Monday', 'mon', 'Tues:' at the start of a heading -> (0..6, the rest), else (None, text)."""
    m = re.match(r"\s*([A-Za-z]+)\.?\s*[:\-–—]?\s*(.*)", text)
    if m:
        word = m.group(1).lower()
        word = {"weds": "wed", "thur": "thu", "thurs": "thu"}.get(word, word)
        for i, name in enumerate(WEEKDAYS):
            if len(word) >= 3 and name.startswith(word):
                return i, m.group(2).strip()
    return None, text.strip()


def _heading(text):
    """A day heading -> {name, weekday}: 'Monday - Push' -> Push on Mondays, 'Day 2: Legs' -> Legs."""
    text = text.strip().strip(":").strip()
    day, rest = _weekday(text)
    rest = re.sub(r"^(?:day|workout|session)\s*\d+\s*[:\-–—]?\s*", "", rest, flags=re.I).strip() or rest
    name = rest or (WEEKDAYS[day].title() if day is not None else text)
    return {"name": name[:60], "weekday": day, "items": []}


def _item(text):
    """One exercise line -> {exercise, sets, reps, weight (kg), kind, text}, or None if it isn't one."""
    m = _ITEM.fullmatch(text)
    if m:
        w, wu = m.group("w") or m.group("w2"), (m.group("wu") or m.group("wu2") or "").lower()
        kg = None if w is None else float(w) * LB if wu.startswith("lb") else float(w) if wu else kg_in(float(w))
        timed = bool(m.group("secs"))
        return {"exercise": m.group("name").strip(" -–:,").strip(), "sets": int(m.group("sets")),
                "reps": None if timed else int(m.group("reps")), "weight": kg,
                "kind": "timed" if timed else None, "text": text}
    m = _CARDIO.fullmatch(text)
    if m:
        unit = m.group("unit").lower()
        kind = "cardio" if unit[0] in "km" and not unit.startswith("min") else "timed"
        return {"exercise": m.group("name").strip(" -–:,").strip(), "sets": 1, "reps": None, "weight": None,
                "kind": kind, "text": text}
    known = find_exercise(text)
    if known and known["name"].lower() == text.lower().strip():
        return {"exercise": known["name"], "sets": 1, "reps": None, "weight": None, "kind": None, "text": text}
    return None


def _parse_csv(text):
    import csv
    import io
    rows = list(csv.DictReader(io.StringIO(text)))
    days, skipped = {}, []
    for r in rows:
        r = {str(k or "").strip().lower(): str(v or "").strip() for k, v in r.items()}
        ex = r.get("exercise") or r.get("name")
        if not ex:
            continue
        head = r.get("day") or r.get("workout") or r.get("session") or "Workout"
        day = days.setdefault(head.lower(), _heading(head))
        try:
            sets = int(float(r.get("sets") or 1))
            reps = int(float(r["reps"])) if r.get("reps") else None
            w = r.get("weight") or ""
            num = re.match(rf"\s*({_NUM})\s*(kgs?|lbs?)?", w, re.I)
            kg = None
            if num:
                kg = float(num.group(1)) * LB if (num.group(2) or "").lower().startswith("lb") \
                    else float(num.group(1)) if num.group(2) else kg_in(float(num.group(1)))
        except ValueError:
            skipped.append(", ".join(v for v in r.values() if v))
            continue
        day["items"].append({"exercise": ex, "sets": sets, "reps": reps, "weight": kg, "kind": None,
                             "text": f"{ex} {sets}×{reps or '-'}" + (f" @ {weight_text(kg)}" if kg else "")})
    return list(days.values()), skipped


def parse_plan(text, default_name="Workout"):
    """
    Read a workout plan from text: day headings ('Monday - Push', 'Day 2: Legs', 'Upper') each followed
    by exercise lines ('Bench press 3x8 @ 60', 'Squat 5 sets of 5 100kg', 'Plank 3x45s', 'Run 5 km'),
    or one line per day ('Mon: Bench 3x8 @60, Squat 5x5'). A CSV with an Exercise column (and Day,
    Sets, Reps, Weight) works too. Weights without a unit are in the user's unit.
    Returns (days, skipped lines): days are [{name, weekday (0-6 or None), items}].
    """
    text = (text or "").replace("\r\n", "\n").lstrip("﻿")
    first = next((ln for ln in text.split("\n") if ln.strip()), "")
    if "," in first and re.search(r"\b(exercise|name)\b", first, re.I):
        days, skipped = _parse_csv(text)
    else:
        days, skipped, current = [], [], None
        for raw in text.split("\n"):
            line = _BULLET.sub("", raw).strip()
            if not line or line.startswith("#") and not line.lstrip("#").strip():
                continue
            line = line.lstrip("#").strip()
            head, sep, rest = line.partition(":")
            parts = [p.strip() for p in re.split(r"[,;]", rest) if p.strip()] if sep else []
            inline = [_item(p) for p in parts]
            if parts and all(inline):                # 'Mon: Bench 3x8 @60, Squat 5x5': a whole day
                current = _heading(head)
                current["items"] = inline
                days.append(current)
                continue
            item = _item(line)
            if item:
                if current is None:
                    current = {"name": default_name, "weekday": None, "items": []}
                    days.append(current)
                current["items"].append(item)
            elif len(line) <= 60 and (line.endswith(":") or _weekday(line)[0] is not None or (
                    len(line.split()) <= 6 and re.fullmatch(r"(?:(?:day|week|workout|session)\s*\d+\b)?\D*", line, re.I))):
                current = _heading(line)
                days.append(current)
            else:
                skipped.append(line)
    days = [d for d in days if d["items"]]
    seen = {}
    for d in days:                                   # plan names are unique: "Upper", "Upper 2"
        n = seen[d["name"].lower()] = seen.get(d["name"].lower(), 0) + 1
        if n > 1:
            d["name"] = f"{d['name']} {n}"
    return days, skipped


def _fit_day(day, need, lo, hi, now):
    """The first free stretch of `need` slots on a day between slots lo..hi (none in the past), or None."""
    from venato import tools
    start = max(lo, tools._first_future_slot(day.isoformat()))
    for s, e in store.free_runs(day.isoformat(), start, hi, now=now):
        if e - s >= need:
            return s, s + need
    return None


def fit_plan(days, start, weeks=4, minutes=60, earliest="07:00", latest="21:00"):
    """
    Pick a time for each plan day in each week (7 days from `start`): on its weekday if it has one,
    else spread through the week (3 days -> 1st, 3rd, 5th day), moving to the nearest free day when
    the Plan is full. Returns ([(date, start slot, end slot, day)], [(week start, day name)] that didn't fit).
    """
    from venato import tools
    if not days:
        raise WorkoutError("There are no workouts in that plan.")
    if len(days) > 7:
        raise WorkoutError("That plan has more than 7 workouts a week; split it into weeks.")
    start = store._as_date(start)
    need = max(1, -(-int(minutes) // 30))
    lo, hi = tools._window(earliest, latest)
    if hi - lo < need:
        raise WorkoutError("The window between those times is shorter than one workout.")
    now = tools._now()
    k = len(days)
    placed, missed = [], []
    for w in range(max(1, int(weeks))):
        week = [start + timedelta(days=7 * w + i) for i in range(7)]
        used = set()
        fixed = [d for d in days if d["weekday"] is not None]
        order = fixed + [d for d in days if d["weekday"] is None]
        targets = [i * 7 // k for i in range(k)]         # evenly spread days of the week
        for d in fixed:                                  # a fixed day takes the nearest spread day
            pos = next(i for i, x in enumerate(week) if x.weekday() == d["weekday"])
            targets.remove(min(targets, key=lambda t: abs(t - pos)))
        free_targets = iter(targets)
        for d in order:
            if d["weekday"] is not None:
                target = next(i for i, x in enumerate(week) if x.weekday() == d["weekday"])
            else:
                target = next(free_targets)
            got = None
            for step in range(7):
                for i in ((target + step, target - step) if step else (target,)):
                    if 0 <= i < 7 and i not in used and (got := _fit_day(week[i], need, lo, hi, now)):
                        used.add(i)
                        placed.append((week[i], got[0], got[1], d))
                        break
                if got:
                    break
            if not got:
                missed.append((week[0], d["name"]))
    placed.sort(key=lambda p: (p[0], p[1]))
    return placed, missed


def _plan_details(day):
    return "\n".join(f"- {it['text']}" for it in day["items"])


def schedule_plan(days, start, weeks=4, minutes=60, earliest="07:00", latest="21:00", category=None,
                  confirmed=False):
    """Save the uploaded days as plans and put each one into the timetable's Plan; previewed first."""
    from venato import tools
    try:
        placed, missed = fit_plan(days, start, weeks, minutes, earliest, latest)
    except WorkoutError as e:
        raise tools.ToolError(str(e))
    cid = store.resolve_category(category=category) if category else None
    if cid is None:
        cid = store.resolve_category(category="Exercise") or store.resolve_category(label="Gym")
    if cid is None:
        raise tools.ToolError("Pick a category for the workouts.")
    if not placed:
        raise tools.ToolError(f"There's no free {minutes}-minute gap between {earliest} and {latest} "
                              "on those days. Try a wider time window or shorter workouts.")
    names = ", ".join(d["name"] for d in days)
    lines = "\n".join(f"- {tools.nice_day(d.isoformat())} {store.slot_time(s)}–{store.slot_time(e)} {day['name']}"
                      for d, s, e, day in placed)
    short = ""
    if missed:
        short = f"\n\n{len(missed)} didn't fit: " + "; ".join(
            f"{n} (week of {tools.nice_day(w.isoformat())})" for w, n in missed)
    summary = (f"Save the plans {names} and add {len(placed)} workouts to your Plan "
               f"({tools._cat_names().get(cid, 'Exercise')}):\n\n{lines}{short}")
    if not confirmed:
        return tools.Result("", pending=tools.Pending(summary, lambda: schedule_plan(
            days, start, weeks, minutes, earliest, latest, category, True)))
    for d in days:
        save_plan(d["name"], d["items"])
    now = tools._now()
    for d, s, e, day in placed:
        store.paint(d.isoformat(), store.live_track(d.isoformat(), now), s, e,
                    {"label": day["name"], "category_id": cid, "details": _plan_details(day)})
    return tools.Result(f"Saved {len(days)} plan(s) and added {len(placed)} workouts to your Plan.", changed=True)


# --- Numbers: 1RM, PBs, volume ---

def one_rep_max(weight, reps):
    """Estimated one-rep max (Epley), for 1-12 reps; None otherwise."""
    if not weight or not reps or reps < 1 or reps > 12:
        return None
    return weight if reps == 1 else weight * (1 + reps / 30)


def personal_bests():
    """{exercise: {heaviest, best_1rm, most_reps, longest_km, longest_secs, dates...}} from working sets."""
    out = {}
    for s in all_sets():
        if s["warmup"]:
            continue
        pb = out.setdefault(s["exercise"], {"kind": s["kind"]})
        def better(key, value, date):
            if value is not None and (key not in pb or value > pb[key][0]):
                pb[key] = (value, date)
        better("heaviest", s["weight"], s["date"])
        better("best_1rm", one_rep_max(s["weight"], s["reps"]), s["date"])
        better("most_reps", s["reps"], s["date"])
        better("longest_km", s["distance"], s["date"])
        better("longest_secs", s["seconds"], s["date"])
    return out


def progress(exercise_id):
    """[(date, best estimated 1RM or top weight, top weight, total reps)] per workout day."""
    by_day = {}
    for s in all_sets():
        if s["exercise_id"] != exercise_id or s["warmup"]:
            continue
        d = by_day.setdefault(s["date"], {"orm": None, "top": None, "reps": 0, "km": 0.0})
        orm = one_rep_max(s["weight"], s["reps"])
        if orm and (d["orm"] is None or orm > d["orm"]):
            d["orm"] = orm
        if s["weight"] is not None and (d["top"] is None or s["weight"] > d["top"]):
            d["top"] = s["weight"]
        d["reps"] += s["reps"] or 0
        d["km"] += s["distance"] or 0
    return [(day, v["orm"], v["top"], v["reps"], v["km"]) for day, v in sorted(by_day.items())]


def weekly_volume(first, last):
    """Working sets and tonnage (kg × reps) per muscle group between two dates."""
    out = {}
    for s in all_sets(first, last):
        if s["warmup"]:
            continue
        m = out.setdefault(s["muscle"] or "Other", {"sets": 0, "tonnage": 0.0})
        m["sets"] += 1
        m["tonnage"] += (s["weight"] or 0) * (s["reps"] or 0)
    return out


def summary(wid):
    """'Bench press 3×8 @ 60 kg, Squat 5×5 @ 100 kg' and totals."""
    groups = {}
    for s in sets_of(wid):
        if s["warmup"]:
            continue
        groups.setdefault(s["exercise"], []).append(s)
    parts = []
    for name, ss in groups.items():
        top = max((x["weight"] or 0) for x in ss)
        reps = [x["reps"] for x in ss if x["reps"]]
        dist = sum(x["distance"] or 0 for x in ss)
        if dist:
            parts.append(f"{name} {km_out(dist):g} {units()[1]}")
        elif reps:
            same = len(set(reps)) == 1
            parts.append(f"{name} {len(ss)}×{reps[0] if same else '/'.join(map(str, reps))}"
                         + (f" @ {weight_text(top)}" if top else ""))
        else:
            secs = sum(x["seconds"] or 0 for x in ss)
            parts.append(f"{name} {len(ss)} set{'s' * (len(ss) != 1)}" + (f", {secs // 60} min" if secs else ""))
    return ", ".join(parts)


# --- Habit link ---

def _tick_habit(day):
    """Logging a workout can tick a habit (Settings → Workouts), e.g. 'Gym'."""
    name = (store.load_settings().get("workouts") or {}).get("habit")
    if not name:
        return
    found = store.find_habit(name)
    if found:
        with store.db() as conn:
            store.set_habit_done(conn, found[0], day.isoformat(), True)


def set_habit_link(name):
    store.save_settings(workouts={**(store.load_settings().get("workouts") or {}), "habit": name or None})


# --- The assistant ---

def tool_log(exercises=None, date=None, title=None, minutes=None, notes=None):
    """exercises: [{name, sets, reps, weight, distance, minutes}] in the user's units."""
    from venato import tools
    if not exercises:
        raise tools.ToolError("Say which exercises (with sets, reps and weight, or distance / time).")
    try:
        day = store._as_date(date) if date else store.local_today()
        wid = workout_on(day) if not title else None
        wid = wid or add_workout(day, title or "Workout", minutes=minutes, notes=notes)
        for ex in exercises:
            e = exercise_or_new(ex.get("name"), "cardio" if ex.get("distance") else None)
            add_sets(wid, e["id"], ex.get("sets") or 1, ex.get("reps"), kg_in(ex.get("weight")),
                     km_in(ex.get("distance")), int(float(ex["minutes"]) * 60) if ex.get("minutes") else None)
    except (WorkoutError, ValueError) as e:
        raise tools.ToolError(str(e))
    return tools.Result(f"Logged on {day.isoformat()}: {summary(wid)}.", changed=True)


def tool_list(days=14):
    from venato import tools
    today = store.local_today()
    rows = workouts(today - timedelta(days=int(days) - 1), today)
    if not rows:
        return tools.Result(f"No workouts in the last {days} days.")
    return tools.Result("\n".join(f"- {w['date']} {w['title']}: {summary(w['id']) or 'no sets'}" for w in rows))


def tool_progress(exercise):
    from venato import tools
    e = find_exercise(exercise)
    if not e:
        raise tools.ToolError(f"No exercise called '{exercise}'.")
    rows = progress(e["id"])
    if not rows:
        return tools.Result(f"No {e['name']} logged yet.")
    lines = [f"- {d}: top {weight_text(top) or '-'}" + (f", est. 1RM {weight_text(orm)}" if orm else "")
             + (f", {reps} reps" if reps else "") for d, orm, top, reps, km in rows[-12:]]
    return tools.Result(f"{e['name']} (last {len(lines)} sessions):\n" + "\n".join(lines))


def tool_bests():
    from venato import tools
    pbs = personal_bests()
    if not pbs:
        return tools.Result("No workouts logged yet.")
    lines = []
    for name, pb in sorted(pbs.items()):
        bits = []
        if "heaviest" in pb:
            bits.append(f"heaviest {weight_text(pb['heaviest'][0])}")
        if "best_1rm" in pb:
            bits.append(f"est. 1RM {weight_text(pb['best_1rm'][0])}")
        if "most_reps" in pb and pb["kind"] == "bodyweight":
            bits.append(f"{pb['most_reps'][0]} reps")
        if "longest_km" in pb:
            bits.append(f"longest {km_out(pb['longest_km'][0]):g} {units()[1]}")
        if bits:
            lines.append(f"- {name}: " + ", ".join(bits))
    return tools.Result("\n".join(lines) or "No personal bests yet.")


QUICK = re.compile(r"(?:did\s+|log\s+)?(.+?)\s+(\d{1,2})\s*[x×]\s*(\d{1,3})"
                   r"(?:\s*(?:@|at)\s*(\d+(?:\.\d+)?)\s*(kg|kgs|lb|lbs)?)?")


def _quick(text, day):
    """'bench 3x8 at 60', 'squat 5x5 @ 100kg', 'pull-ups 3x10' -> sets in today's workout."""
    m = QUICK.fullmatch(text)
    if not m:
        return None
    e = find_exercise(m.group(1))
    if not e:
        return None                              # not a known exercise: leave it to Claude
    from venato import tools
    weight = float(m.group(4)) if m.group(4) else None
    if weight is not None and m.group(5) in ("lb", "lbs"):
        kg = weight * LB
    elif weight is not None and m.group(5) in ("kg", "kgs"):
        kg = weight
    else:
        kg = kg_in(weight)
    wid = workout_on(day, "Workout")
    add_sets(wid, e["id"], int(m.group(2)), int(m.group(3)), kg)
    return tools.Result(f"{e['name']} {m.group(2)}×{m.group(3)}" + (f" @ {weight_text(kg)}" if kg else "")
                        + " added to today's workout.", changed=True)


def _context():
    today = store.local_today()
    week = workouts(store.week_start_of(today), today)
    last = workouts(today - timedelta(days=60), today)[:1]
    text = f"{len(week)} workout(s) this week. Units: {units()[0]}, {units()[1]}."
    if last:
        text += f" Last: {last[0]['date']} {last[0]['title']} ({summary(last[0]['id']) or 'no sets'})."
    return text


PROMPT = """- Workouts: a log of workouts made of sets (the Workouts page). "did bench 3x8 at 60 and squats 5x5 at 100"
  -> log_workout(exercises=[{name:"Bench press", sets:3, reps:8, weight:60}, {name:"Squat", sets:5, reps:5,
  weight:100}]) in the user's units (see [Now]); a run -> {name:"Running", distance:5, minutes:28}. Sets go
  into today's workout unless they give a date or title. list_workouts, exercise_progress(exercise) and
  personal_bests answer "how's my bench going?", "what's my best deadlift?"."""

TOOLS = [
    ("log_workout", "Log exercises (sets, reps, weight; or distance / minutes) into a workout on a date (default today).",
     {"type": "object", "properties": {
         "exercises": {"type": "array", "items": {"type": "object", "properties": {
             "name": {"type": "string"}, "sets": {"type": "integer"}, "reps": {"type": "integer"},
             "weight": {"type": "number", "description": "in the user's weight unit"},
             "distance": {"type": "number", "description": "in the user's distance unit"},
             "minutes": {"type": "number"}}, "required": ["name"]}},
         "date": {"type": "string"}, "title": {"type": "string"}, "minutes": {"type": "number"},
         "notes": {"type": "string"}}, "required": ["exercises"]}, tool_log),
    ("list_workouts", "Workouts in the last N days (default 14) with what was done.",
     {"type": "object", "properties": {"days": {"type": "integer"}}, "required": []}, tool_list),
    ("exercise_progress", "How an exercise has gone over time (top weight, estimated 1RM, reps).",
     {"type": "object", "properties": {"exercise": {"type": "string"}}, "required": ["exercise"]}, tool_progress),
    ("personal_bests", "Personal bests for every exercise.",
     {"type": "object", "properties": {}, "required": []}, tool_bests),
]


def _page():
    from venato.ui import workouts as ui
    ui.render_page()


def _home():
    from venato.ui import workouts as ui
    ui.render_home()


BLOCK = Block("workouts", "Workouts", ":material/fitness_center:",
              "Log workouts set by set, save plans, and track personal bests, 1RMs and weekly volume.",
              group="Health & body", page=_page, home=_home, tools=TOOLS, prompt=PROMPT, context=_context,
              quick=[_quick], schema=SCHEMA, order=80)
