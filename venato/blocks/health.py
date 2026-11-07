"""
Health data: daily numbers (steps, sleep, resting heart rate, HRV, active calories, weight,
Whoop recovery and strain) and workouts imported from the files other apps export:

  Apple Health  Health app → profile → Export All Health Data: export.zip (or its export.xml).
                Read with defusedxml, streamed, so a multi-GB export doesn't fill memory.
  Google Fit    Google Takeout → Fit: "Daily activity metrics.csv".
  Strava        Settings → My Account → Download your data: activities.csv.
  Whoop         App → Settings → Data export: physiological_cycles.csv, sleeps.csv, workouts.csv.

None of these formats is formally documented and they change, so the CSV imports guess the
columns from their names and show a preview where you can change the mapping before
anything is saved. Re-importing the same file never doubles up (rows have a source id).
Workouts go into the Workouts block's log (with their source).

Nothing here talks to the internet: Google Fit's APIs shut down in 2026, and Apple Health
has no web API, so files are the only way that works for everyone.
"""

import csv
import hashlib
import io
import re
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from venato import store
from venato.blocks import Block

METRICS = {   # key: (label, unit, how a day's values combine)
    "steps": ("Steps", "", "sum"),
    "active_kcal": ("Active calories", "kcal", "sum"),
    "distance_km": ("Distance", "km", "sum"),
    "sleep_h": ("Sleep", "h", "sum"),
    "resting_hr": ("Resting heart rate", "bpm", "avg"),
    "hrv": ("HRV", "ms", "avg"),
    "weight_kg": ("Weight", "kg", "last"),
    "recovery": ("Recovery", "%", "avg"),
    "strain": ("Strain", "", "avg"),
}
SOURCES = ["Apple Health", "Google Fit", "Strava", "Whoop", "Other"]
MAX_FILE = 4_000_000_000          # bytes: a big Apple Health export is a few GB

SCHEMA = """
CREATE TABLE IF NOT EXISTS hl_metrics (
    date    TEXT NOT NULL,
    metric  TEXT NOT NULL,
    value   REAL NOT NULL,
    source  TEXT NOT NULL,
    PRIMARY KEY (date, metric, source)
);
"""


class HealthError(ValueError):
    pass


# --- Storing and reading ---

def save_metrics(rows, source):
    """rows: (date, metric, value). Replaces that source's value for the day (so re-imports update)."""
    rows = [(str(d), m, float(v), source) for d, m, v in rows if m in METRICS and v is not None]
    with store.db() as conn:
        conn.executemany("INSERT OR REPLACE INTO hl_metrics (date, metric, value, source) VALUES (?, ?, ?, ?)", rows)
    return len(rows)


def series(metric, first, last):
    """{date: value} for a metric; with several sources on a day, the first in SOURCES order wins."""
    with store.db() as conn:
        rows = conn.execute("SELECT date, value, source FROM hl_metrics WHERE metric = ? AND date BETWEEN ? AND ? "
                            "ORDER BY date", (metric, str(first), str(last))).fetchall()
    out, rank = {}, {}
    for d, v, s in rows:
        r = SOURCES.index(s) if s in SOURCES else len(SOURCES)
        if d not in out or r < rank[d]:
            out[d], rank[d] = v, r
    return out


def latest(days=7):
    """Each metric's average over the last `days` days (weight: the latest), for metrics that have data."""
    today = store.local_today()
    out = {}
    for m, (_, _, how) in METRICS.items():
        s = series(m, today - timedelta(days=days - 1), today)
        if s:
            out[m] = list(s.values())[-1] if how == "last" else sum(s.values()) / len(s)
    return out


def clear(source):
    with store.db() as conn:
        conn.execute("DELETE FROM hl_metrics WHERE source = ?", (source,))
        conn.execute("DELETE FROM wk_workouts WHERE source = ?", (source.lower(),))


def counts():
    with store.db() as conn:
        m = dict(conn.execute("SELECT source, COUNT(*) FROM hl_metrics GROUP BY source").fetchall())
        w = dict(conn.execute("SELECT source, COUNT(*) FROM wk_workouts WHERE source != 'manual' GROUP BY source").fetchall())
    return {s: (m.get(s, 0), w.get(s.lower(), 0)) for s in SOURCES if m.get(s) or w.get(s.lower())}


def _workout(source, source_id, day, title, minutes=None, km=None, kcal=None, start=None, notes=None):
    from venato.blocks import workouts as wk
    bits = [notes] if notes else []
    if kcal:
        bits.append(f"{kcal:.0f} kcal")
    with store.db() as conn:
        seen = conn.execute("SELECT 1 FROM wk_workouts WHERE source = ? AND source_id = ?",
                            (source.lower(), source_id)).fetchone()
    if seen:
        return False
    wid = wk.add_workout(day, title, start, " · ".join(bits) or None,
                         round(minutes, 1) if minutes else None, None, source.lower(), source_id)
    if km:
        ex = wk.exercise_or_new(title.split(" (")[0], "cardio")
        wk.add_sets(wid, ex["id"], 1, distance=round(km, 3), seconds=int(minutes * 60) if minutes else None)
    return True


# --- Apple Health ---

APPLE = {   # Record type: (metric, how a day combines)
    "HKQuantityTypeIdentifierStepCount": ("steps", "sum"),
    "HKQuantityTypeIdentifierActiveEnergyBurned": ("active_kcal", "sum"),
    "HKQuantityTypeIdentifierDistanceWalkingRunning": ("distance_km", "sum"),
    "HKQuantityTypeIdentifierRestingHeartRate": ("resting_hr", "avg"),
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": ("hrv", "avg"),
    "HKQuantityTypeIdentifierBodyMass": ("weight_kg", "last"),
}
ASLEEP = ("HKCategoryValueSleepAnalysisAsleep", "HKCategoryValueSleepAnalysisAsleepCore",
          "HKCategoryValueSleepAnalysisAsleepDeep", "HKCategoryValueSleepAnalysisAsleepREM",
          "HKCategoryValueSleepAnalysisAsleepUnspecified")


def _apple_time(text):
    """'2026-01-05 08:00:00 +0000' -> an aware datetime in the user's time zone."""
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S %z").astimezone(store.tz())


def _unit_value(value, unit):
    v = float(value)
    return {"lb": v * 0.45359237, "g": v / 1000, "mi": v * 1.609344, "m": v / 1000, "Cal": v, "kJ": v / 4.184,
            "s": v / 60, "hr": v * 60, "h": v * 60}.get(unit, v)


def _open_apple(path_or_file):
    """A binary stream of export.xml, from a path or an upload (zip or xml)."""
    f = open(path_or_file, "rb") if isinstance(path_or_file, (str, Path)) else path_or_file
    head = f.read(4)
    f.seek(0)
    if head.startswith(b"PK"):
        z = zipfile.ZipFile(f)
        names = [n for n in z.namelist() if n.endswith("export.xml") and "cda" not in n.lower()]
        if not names:
            raise HealthError("That zip has no export.xml in it.")
        info = z.getinfo(names[0])
        if info.file_size > MAX_FILE:
            raise HealthError("That export is too big to read.")
        return z.open(info)
    return f


def read_apple(path_or_file, since=None):
    """Read an Apple Health export: (metric rows, workouts). since: only from this date on."""
    from defusedxml.ElementTree import iterparse
    since = str(since) if since else "0000"
    per = {}             # (date, metric, source app) -> [values]
    sleep = {}           # (date, source app) -> minutes; a night counts for the day it ends
    workouts = []
    try:
        stream = _open_apple(path_or_file)
    except (zipfile.BadZipFile, OSError):
        raise HealthError("Couldn't open that file. Is it the export.zip or export.xml?") from None
    try:
        root = None
        for event, el in iterparse(stream, events=("start", "end"), forbid_dtd=False, forbid_entities=True,
                                   forbid_external=True):
            if event == "start":
                if root is None:
                    root = el
                continue
            tag = el.tag
            if tag == "Record":
                t = el.get("type")
                if t in APPLE or t == "HKCategoryTypeIdentifierSleepAnalysis":
                    try:
                        start, end = _apple_time(el.get("startDate")), _apple_time(el.get("endDate"))
                    except (TypeError, ValueError):
                        root.clear()
                        continue
                    app = el.get("sourceName") or ""
                    if t == "HKCategoryTypeIdentifierSleepAnalysis":
                        if el.get("value") in ASLEEP and end.date().isoformat() >= since:
                            k = (end.date().isoformat(), app)
                            sleep[k] = sleep.get(k, 0) + (end - start).total_seconds() / 60
                    elif start.date().isoformat() >= since:
                        metric, _ = APPLE[t]
                        try:
                            v = float(el.get("value"))
                        except (TypeError, ValueError):
                            root.clear()
                            continue
                        unit = el.get("unit")
                        if metric in ("weight_kg", "distance_km", "active_kcal"):
                            v = _unit_value(v, unit)
                        per.setdefault((start.date().isoformat(), metric, app), []).append(v)
                root.clear()
            elif tag == "Workout":
                try:
                    start = _apple_time(el.get("startDate"))
                except (TypeError, ValueError):
                    root.clear()
                    continue
                if start.date().isoformat() >= since:
                    kind = re.sub(r"(?<!^)(?=[A-Z])", " ", (el.get("workoutActivityType") or "").replace(
                        "HKWorkoutActivityType", "")) or "Workout"
                    minutes = _unit_value(el.get("duration") or 0, el.get("durationUnit") or "min") or None
                    km = kcal = None
                    if el.get("totalDistance"):
                        km = _unit_value(el.get("totalDistance"), el.get("totalDistanceUnit") or "km")
                    if el.get("totalEnergyBurned"):
                        kcal = float(el.get("totalEnergyBurned"))
                    for s in el.iter("WorkoutStatistics"):       # newer exports keep the totals here
                        st_t, total = s.get("type") or "", s.get("sum")
                        if total and "Distance" in st_t and km is None:
                            km = _unit_value(total, s.get("unit") or "km")
                        if total and "ActiveEnergyBurned" in st_t and kcal is None:
                            kcal = float(total)
                    workouts.append({"date": start.date().isoformat(), "start": f"{start:%H:%M}", "title": kind.strip(),
                                     "minutes": minutes, "km": km or None, "kcal": kcal,
                                     "id": f"{el.get('startDate')}|{kind}"})
                root.clear()
    except HealthError:
        raise
    except Exception as e:
        raise HealthError(f"Couldn't read that export ({type(e).__name__}). Is it the export.zip or export.xml?") from None
    finally:
        stream.close()

    # Steps etc. are recorded by both the phone and the watch: take the biggest source each day, not the total.
    days = {}
    for (d, metric, app), vals in per.items():
        how = APPLE_HOW[metric]
        v = sum(vals) if how == "sum" else vals[-1] if how == "last" else sum(vals) / len(vals)
        k = (d, metric)
        if how == "sum":
            days[k] = max(days.get(k, 0), v)
        else:
            days.setdefault(k, []).append(v)
    rows = [(d, m, v if not isinstance(v, list) else sum(v) / len(v)) for (d, m), v in days.items()]
    nights = {}
    for (d, app), mins in sleep.items():
        nights[d] = max(nights.get(d, 0), mins)
    rows += [(d, "sleep_h", round(m / 60, 2)) for d, m in nights.items() if m >= 30]
    return rows, workouts


APPLE_HOW = {m: how for m, how in APPLE.values()}


def import_apple(path_or_file, since=None):
    rows, workouts = read_apple(path_or_file, since)
    n = save_metrics(rows, "Apple Health")
    w = sum(_workout("Apple Health", x["id"], x["date"], x["title"], x["minutes"], x["km"], x["kcal"], x["start"])
            for x in workouts)
    return {"days": len({r[0] for r in rows}), "values": n, "workouts": w}


# --- CSV exports (Google Fit, Strava, Whoop) ---

PROFILES = {   # source: {"kind": metrics/workouts, field: [words that name its column]}
    "Google Fit": {"kind": "metrics", "date": ["date"], "steps": ["step count", "steps"],
                   "active_kcal": ["calories"], "distance_km": ["distance (m)", "distance"],
                   "resting_hr": ["average heart rate", "heart rate"], "weight_kg": ["average weight", "weight"]},
    "Whoop": {"kind": "metrics", "date": ["cycle start", "start time", "date"], "recovery": ["recovery score", "recovery"],
              "resting_hr": ["resting heart rate"], "hrv": ["heart rate variability", "hrv"],
              "strain": ["day strain", "strain"], "sleep_h": ["asleep duration", "sleep duration"]},
    "Whoop workouts": {"kind": "workouts", "date": ["workout start", "start time", "date"],
                       "title": ["activity name", "sport", "activity"], "minutes": ["duration"],
                       "kcal": ["energy burned", "calories"], "km": ["distance"]},
    "Strava": {"kind": "workouts", "date": ["activity date", "start date", "date"], "id": ["activity id", "id"],
               "title": ["activity name", "name"], "type": ["activity type", "type"],
               "minutes": ["moving time", "elapsed time"], "km": ["distance"], "kcal": ["calories"]},
}
CSV_SOURCE = {"Google Fit": "Google Fit", "Whoop": "Whoop", "Whoop workouts": "Whoop", "Strava": "Strava"}


def read_csv(raw):
    """(columns, rows) from a CSV's bytes. Repeated column names (Strava has two 'Distance's) keep the first."""
    if len(raw) > 200_000_000:
        raise HealthError("That file is too big (over 200 MB).")
    text = raw.decode("utf-8-sig", errors="replace") if isinstance(raw, bytes) else raw
    try:
        dialect = csv.Sniffer().sniff(text[:5000], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect=dialect)
    try:
        head = next(reader)
    except StopIteration:
        raise HealthError("That file is empty.") from None
    cols, idx = [], []
    for i, c in enumerate(head):
        c = c.strip()
        if c and c not in cols:
            cols.append(c)
            idx.append(i)
    rows = [{c: (r[i] if i < len(r) else "") for c, i in zip(cols, idx)} for r in reader if any(x.strip() for x in r)]
    if not rows:
        raise HealthError("No rows found in that file.")
    return cols, rows


def guess_mapping(profile, columns):
    p = PROFILES[profile]
    low = {c: c.lower() for c in columns}
    out = {}
    for field, words in p.items():
        if field == "kind":
            continue
        out[field] = next((c for w in words for c, l in low.items() if w in l), None)
    return out


def _num(text):
    t = str(text or "").strip().replace(",", "")
    if not t:
        return None
    if re.fullmatch(r"\d+:\d{2}(:\d{2})?", t):                  # 1:02:03 or 45:10
        parts = [int(x) for x in t.split(":")]
        return (parts[0] * 60 + parts[1] + (parts[2] / 60 if len(parts) > 2 else 0)) if len(parts) == 3 \
            else parts[0] + parts[1] / 60
    try:
        return float(re.sub(r"[^\d.\-]", "", t))
    except ValueError:
        return None


DATE_FORMATS = ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y", "%d/%m/%Y %H:%M",
                "%b %d, %Y, %I:%M:%S %p", "%b %d, %Y", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ")


def _when(text):
    t = re.sub(r"(\.\d+)?([+-]\d{2}:?\d{2}|Z)$", "", str(text or "").strip()) if "T" in str(text) else str(text or "").strip()
    t = t.replace(" ", " ")
    for f in DATE_FORMATS:
        try:
            return datetime.strptime(t, f)
        except ValueError:
            continue
    raise HealthError(f"Couldn't read the date '{str(text)[:30]}'.")


def convert(profile, rows, mapping):
    """Turn CSV rows into (metric rows, workouts, problems) using the mapping (field -> column)."""
    p = PROFILES[profile]
    metrics, workouts, problems = [], [], []
    for i, row in enumerate(rows, 1):
        try:
            if not mapping.get("date"):
                raise HealthError("Pick the date column.")
            when = _when(row.get(mapping["date"]))
        except HealthError as e:
            problems.append(f"Row {i}: {e}")
            continue
        day = when.date().isoformat()
        get = {f: _num(row.get(c)) for f, c in mapping.items() if c and f not in ("date", "title", "type", "id")}
        if p["kind"] == "metrics":
            for f, v in get.items():
                if v is None or f not in METRICS:
                    continue
                if f == "distance_km" and "(m)" in (mapping[f] or "").lower():
                    v /= 1000
                if f == "sleep_h":
                    v = v / 60 if "min" in (mapping[f] or "").lower() or v > 24 else v
                metrics.append((day, f, v))
        else:
            title = (row.get(mapping.get("title")) or "").strip() if mapping.get("title") else ""
            kind = (row.get(mapping.get("type")) or "").strip() if mapping.get("type") else ""
            mins = get.get("minutes")
            col = (mapping.get("minutes") or "").lower()
            raw = str(row.get(mapping.get("minutes")) or "") if mapping.get("minutes") else ""
            if mins and ":" not in raw and "min" not in col and ("sec" in col or "(s)" in col or profile == "Strava"):
                mins /= 60                                          # Strava's times are in seconds
            km = get.get("km")
            if km and mapping.get("km") and ("meter" in mapping["km"].lower() or "(m)" in mapping["km"].lower()):
                km /= 1000
            sid = (row.get(mapping["id"]) or "").strip() if mapping.get("id") else ""
            sid = sid or hashlib.sha256(f"{profile}|{when}|{title}|{kind}".encode()).hexdigest()[:20]
            name = title or kind or "Workout"
            workouts.append({"date": day, "start": f"{when:%H:%M}" if when.hour or when.minute else None,
                             "title": f"{name} ({kind})" if title and kind and kind.lower() not in title.lower() else name,
                             "minutes": mins, "km": km, "kcal": get.get("kcal"), "id": sid})
    return metrics, workouts, problems


def import_csv(profile, rows, mapping):
    metrics, workouts, problems = convert(profile, rows, mapping)
    source = CSV_SOURCE.get(profile, "Other")
    n = save_metrics(metrics, source)
    w = sum(_workout(source, x["id"], x["date"], x["title"], x["minutes"], x["km"], x["kcal"], x["start"])
            for x in workouts)
    return {"values": n, "workouts": w, "problems": problems}


# --- The assistant ---

def _fmt(metric, v):
    label, unit, _ = METRICS[metric]
    if metric == "weight_kg":
        from venato.blocks import workouts as wk
        return f"{label} {wk.weight_text(v)}"
    return f"{label} {v:,.0f}{(' ' + unit) if unit else ''}" if v >= 100 or metric == "steps" \
        else f"{label} {v:.1f}{(' ' + unit) if unit else ''}"


def tool_health(days=7, metric=None):
    from venato import tools
    days = max(1, min(int(days or 7), 365))
    if metric:
        if metric not in METRICS:
            raise tools.ToolError(f"metric is one of {', '.join(METRICS)}.")
        today = store.local_today()
        s = series(metric, today - timedelta(days=days - 1), today)
        if not s:
            return tools.Result(f"No {METRICS[metric][0].lower()} data in the last {days} days.")
        return tools.Result("\n".join(f"{d}: {v:g}" for d, v in s.items()))
    avg = latest(days)
    if not avg:
        return tools.Result("No health data imported yet (Health data page: Apple Health, Google Fit, Strava, Whoop).")
    return tools.Result(f"Last {days} days (daily average): " + "; ".join(_fmt(m, v) for m, v in avg.items()) + ".")


PROMPT = """- Health data: daily numbers imported from Apple Health, Google Fit, Strava and Whoop exports (steps, sleep,
  resting heart rate, HRV, active calories, distance, weight, recovery, strain); imported workouts are in the
  Workouts log. health_data(days, metric) gives averages, or one metric day by day. Imports are files the user
  adds on the Health data page (there's no live connection)."""

TOOLS = [
    ("health_data", "Imported health numbers: averages over the last N days, or one metric day by day.",
     {"type": "object", "properties": {"days": {"type": "integer"}, "metric": {"type": "string", "enum": list(METRICS)}},
      "required": []}, tool_health),
]


def _context():
    avg = latest(7)
    return ("Health (7-day average): " + "; ".join(_fmt(m, v) for m, v in avg.items()) + ".") if avg else ""


def _page():
    from venato.ui import health as ui
    ui.render_page()


def _home():
    from venato.ui import health as ui
    ui.render_home()


BLOCK = Block("health", "Health data", ":material/monitor_heart:",
              "Import Apple Health, Google Fit, Strava and Whoop exports: steps, sleep, heart rate, recovery, workouts.",
              group="Connections", page=_page, home=_home, tools=TOOLS, prompt=PROMPT, context=_context,
              schema=SCHEMA, order=85)
