"""
The half-marathon training plan: 8 weeks, ending with the race.

How it's built (the usual coaching rules, see HANDOVER.md §5d):
- Sessions per week go 3 → 3 → 4 → 4 → 5 → 5 → 5, then race week.
- Progressive overload: weekly running distance grows about 10-20% a week
  (18 → 20 → 22 km), with an easier "cutback" week (week 4) so the body
  absorbs the work, then builds to a peak in week 6 (30 km, long run 15 km).
- Intensity rises too: easy running only at first, then tempo runs
  (comfortably hard), then intervals, then half-marathon-effort work.
  Most running stays easy (roughly 80/20 easy/hard).
- Strength sessions (from week 3) protect against injury.
- Taper: week 7 drops about 20-25% and race week is light, so you start fresh.

Sessions sit on fixed weekdays (long run on Sunday, race on a Sunday). If the
plan starts mid-week, week 1's sessions are spread over the days left.
No SQL here: store.py saves the sessions this module generates.
"""

from datetime import date, timedelta

PLAN_NAME = "Half marathon"
WEEKS = 8
RACE_KM = 21.1

# What each kind of session means (shown on the Training page and told to Claude).
KINDS = {
    "easy": ("Easy run", "Conversational pace: you could talk in full sentences (effort 3-4 out of 10)."),
    "long": ("Long run", "Slow and steady, easy effort the whole way. Distance matters, not speed."),
    "tempo": ("Tempo run", "Comfortably hard: a few words at a time (effort 7/10). Warm up and cool down easy."),
    "intervals": ("Intervals", "Hard repeats at about 5K effort (8/10), with easy jogs between. Warm up and cool down easy."),
    "race_pace": ("Race pace", "Practise your half-marathon effort (6-7/10): steady, controlled, sustainable."),
    "strength": ("Strength", "30 min: squats, lunges, glute bridges, calf raises, planks, side planks. 2-3 sets each."),
    "shakeout": ("Shakeout", "Very easy, short, with a few relaxed strides. Just to loosen the legs."),
    "race": ("Race day", "Start steady, settle into race effort, and save something for the last 5 km."),
}

# Mon=0 ... Sun=6. (weekday, kind, title, km or None, details)
TEMPLATE = [
    ("Base", [
        (1, "easy", "Easy run", 5, "Easy, conversational pace."),
        (3, "easy", "Easy run + strides", 5, "Easy 5 km, then 4 × 20 s relaxed fast strides with a walk back."),
        (6, "long", "Long run", 8, "Easy pace all the way."),
    ]),
    ("Base", [
        (1, "easy", "Easy run", 5, "Easy, conversational pace."),
        (3, "tempo", "First tempo", 6, "1.5 km easy, 3 km comfortably hard, 1.5 km easy."),
        (6, "long", "Long run", 9, "Easy pace all the way."),
    ]),
    ("Build", [
        (1, "intervals", "400 m repeats", 6, "1.5 km easy, 5 × 400 m hard with 200 m jog, 1.5 km easy."),
        (2, "strength", "Strength", None, "30 min: squats, lunges, glute bridges, calf raises, planks."),
        (3, "easy", "Easy run", 5, "Easy, conversational pace."),
        (6, "long", "Long run", 11, "Easy pace all the way."),
    ]),
    ("Cutback", [
        (1, "tempo", "Tempo intervals", 5, "1 km easy, 2 × 1.5 km comfortably hard with 2 min jog, 1 km easy."),
        (2, "strength", "Strength", None, "30 min: squats, lunges, glute bridges, calf raises, planks."),
        (3, "easy", "Easy run", 5, "Easy. A lighter week so your body absorbs the training."),
        (6, "long", "Long run", 8, "Easy pace. Shorter on purpose."),
    ]),
    ("Build", [
        (0, "strength", "Strength", None, "30 min: squats, lunges, glute bridges, calf raises, planks."),
        (1, "intervals", "800 m repeats", 6.5, "1.5 km easy, 4 × 800 m at 5K effort with 400 m jog, 1.5 km easy."),
        (2, "easy", "Recovery run", 3, "Very easy, short."),
        (4, "easy", "Easy run + strides", 4, "Easy 4 km, then 4 × 20 s strides."),
        (6, "long", "Long run", 12, "Easy pace all the way."),
    ]),
    ("Peak", [
        (0, "strength", "Strength", None, "30 min: squats, lunges, glute bridges, calf raises, planks."),
        (1, "race_pace", "Half-marathon effort", 6.5, "1.5 km easy, 3.5 km at half-marathon effort, 1.5 km easy."),
        (2, "easy", "Recovery run", 3.5, "Very easy, short."),
        (4, "easy", "Easy run", 4, "Easy, conversational pace."),
        (6, "long", "Longest run", 15, "Easy pace. Your biggest run before the race."),
    ]),
    ("Taper", [
        (0, "strength", "Light strength", None, "20 min, lighter than usual: no new exercises, nothing to failure."),
        (1, "race_pace", "Race-pace miles", 6, "1.5 km easy, 2 × 1.6 km at half-marathon effort with 400 m jog, 1 km easy."),
        (2, "easy", "Easy run", 4, "Easy, conversational pace."),
        (4, "easy", "Easy run", 3, "Easy and short."),
        (6, "long", "Long run", 10, "Easy pace. Less distance: you're tapering."),
    ]),
    ("Race week", [
        (1, "easy", "Easy run + strides", 5, "Easy 5 km, then 4 × 20 s strides."),
        (3, "race_pace", "Easy with race effort", 4, "Easy, with 2 km in the middle at half-marathon effort."),
        (5, "shakeout", "Shakeout", 3, "Very easy 3 km and a few strides. Lay out your kit tonight."),
        (6, "race", "Half marathon", RACE_KM, "Start steady, settle into race effort, save something for the last 5 km."),
    ]),
]


# On the timetable: weekday sessions after work, long runs and the race in the morning
# (both changeable on the Training page). Length: about 6.5 min per km plus 15 min to warm up
# and stretch, rounded up to the half hour; strength 30 min.
DEFAULT_TIMES = {"weekday": "18:00", "weekend": "09:00"}
MIN_PER_KM = 6.5


def minutes(session):
    if not session["distance_km"]:
        return 30
    return session["distance_km"] * MIN_PER_KM + 15


def start_time(session, times=None):
    times = {**DEFAULT_TIMES, **(times or {})}
    weekend = date.fromisoformat(session["date"]).weekday() >= 5 or session["kind"] in ("long", "race")
    return times["weekend" if weekend else "weekday"]


def block_details(session):
    km = f"{session['distance_km']:g} km. " if session["distance_km"] else ""
    return f"Training, week {session['week']}: {km}{session['details'] or ''}".strip()


def monday(d):
    return d - timedelta(days=d.weekday())


def plan_start(start):
    """
    The plan's first day. Week 1 is the week containing `start`, unless too few days
    are left in it for week 1's sessions; then the plan starts the next Monday.
    """
    days_left = 7 - start.weekday()
    return start if days_left >= len(TEMPLATE[0][1]) else monday(start) + timedelta(days=7)


def generate(start):
    """
    (start, race_day, sessions) for a plan beginning on `start` (a date).
    sessions: dicts with week, date (ISO), kind, title, distance_km, details, ord.
    """
    start = plan_start(start)
    week1 = monday(start)
    sessions = []
    for w, (_phase, items) in enumerate(TEMPLATE, start=1):
        days = [week1 + timedelta(days=7 * (w - 1) + wd) for wd, *_ in items]
        if w == 1 and days[0] < start:
            # Starting mid-week: spread week 1 over the days left, long run on Sunday.
            left = [start + timedelta(days=i) for i in range(7 - start.weekday())]
            n = len(items)
            days = [left[int(i * (len(left) - 1) / (n - 1) + 0.5)] for i in range(n)] if n > 1 else [left[-1]]
        for i, ((_wd, kind, title, km, details), d) in enumerate(zip(items, days)):
            sessions.append({"week": w, "date": d.isoformat(), "kind": kind, "title": title,
                             "distance_km": km, "details": details, "ord": i})
    race_day = date.fromisoformat(sessions[-1]["date"])
    return start, race_day, sessions


def phase(week):
    """'Base', 'Build', 'Cutback', 'Peak', 'Taper' or 'Race week'."""
    return TEMPLATE[week - 1][0] if 1 <= week <= len(TEMPLATE) else ""


def kind_name(kind):
    return KINDS.get(kind, (kind.title(), ""))[0]
