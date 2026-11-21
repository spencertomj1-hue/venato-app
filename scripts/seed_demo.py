"""
Create a demo data folder full of realistic fake data (for screenshots and trying
Venato out). It never touches your real data: it always writes to a new, empty folder.

    .venv/bin/python scripts/seed_demo.py              # a new temp folder
    .venv/bin/python scripts/seed_demo.py /tmp/demo    # a folder of your choice (must be empty)

Then run the app on it:

    VENATO_DATA_DIR=<folder> .venv/bin/streamlit run app.py
"""

import os
import random
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from venato.system import default_data_dir  # noqa: E402

REAL_DATA = default_data_dir()


def pick_folder():
    folder = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="venato-demo-"))
    if folder == REAL_DATA.resolve():
        sys.exit("That's your real Venato data folder. Pick another folder.")
    if folder.exists() and any(folder.iterdir()):
        sys.exit(f"{folder} isn't empty. Pick an empty or new folder.")
    folder.mkdir(parents=True, exist_ok=True)
    return folder


FOLDER = pick_folder()
os.environ["VENATO_DATA_DIR"] = str(FOLDER)          # before importing store
os.environ.pop("VENATO_DB", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from venato import store  # noqa: E402  (needs VENATO_DATA_DIR set first)

random.seed(7)
TODAY = store.local_today()
MONDAY = store.week_start_of(TODAY)

NOTES = [
    "Good focus in the morning, slow afternoon.", "Long walk by the river after dinner.",
    "Tired after a late night, but the run helped.", "Finished the project draft!",
    "Rainy day, stayed in and read.", "Caught up with friends over pizza.",
    "Too much time on my phone tonight.", "Great gym session, new personal best.",
    None, None, None,
]

# A typical weekday plan, and how it actually went (some drift, like real life).
WEEKDAY_PLAN = [
    ("07:00", "07:30", "Breakfast", "meals"), ("08:00", "08:30", "Commute", "commute"),
    ("09:00", "11:00", "Deep work", "work"), ("11:00", "12:30", "Study", "study"),
    ("12:30", "13:30", "Lunch", "meals"), ("14:00", "16:00", "Project", "projects"),
    ("17:30", "18:30", "Gym", "exercise"), ("19:00", "20:00", "Dinner", "meals"),
    ("20:30", "21:30", "Reading", "reading"), ("23:30", "01:00", "Sleep", "sleep"),
]
WEEKEND_PLAN = [
    ("09:00", "10:00", "Breakfast", "meals"), ("10:30", "12:00", "Run", "exercise"),
    ("13:00", "14:00", "Lunch", "meals"), ("15:00", "18:00", "Friends", "social"),
    ("19:00", "20:00", "Dinner", "meals"), ("21:00", "22:00", "Reading", "reading"),
]


def shifted(t, minutes):
    h, m = map(int, t.split(":"))
    total = h * 60 + m + minutes
    total = max(7 * 60, min(total, 24 * 60 + 60))       # stay on the 07:00-01:00 grid
    return f"{total // 60 % 24:02d}:{total % 60:02d}"


def main():
    store.init_db()                                     # a blank slate: no categories yet
    store.save_settings(wizard_done=True, first_seen=(TODAY - timedelta(days=30)).isoformat())
    from venato.store import categories
    for cid, name, colour, text, grp in categories.EXAMPLE_CATEGORIES:       # what setup would suggest
        store.save_category(cid, name, colour, grp, text)
    for label, cid in categories.EXAMPLE_LABEL_MAP.items():
        store.set_label_default(label, cid)
    from venato.blocks import grades as gr
    chem = gr.add_module("Chemistry 101", 15, "Year 1", 65, "CHEM101")       # each makes its own category
    design = gr.add_module("Design Basics", 15, "Year 1", 70, "DES110")

    # --- Timetable: last week's and this week's Plan (one timeline: the user plans once) ---
    for i in range(-7, 7):
        day = MONDAY + timedelta(days=i)
        plan = WEEKDAY_PLAN if day.weekday() < 5 else WEEKEND_PLAN
        for start, end, label, cat in plan:
            store.paint(day.isoformat(), "plan", store.slot_of(start), store.slot_of(end),
                        {"label": label, "category_id": cat})
    # Days already over: the first confirmed, with corrections (the gym skipped, phone instead of the
    # project for an hour, an unplanned walk); the others left unconfirmed (shown as "assumed").
    s = store.slot_of
    past = [MONDAY + timedelta(days=i) for i in range(-7, 7) if MONDAY + timedelta(days=i) < TODAY]
    for n, day in enumerate(past):
        iso = day.isoformat()
        if n in (0, 1, 3):                                  # confirmed as planned
            store.confirm_day(iso)
        if n == 0:
            store.correct(iso, s("17:30"), s("18:30"), None)
            store.correct(iso, s("14:00"), s("15:00"), {"label": "Phone", "category_id": "distracted"})
            store.correct(iso, s("16:00"), s("17:00"), {"label": "Walk", "category_id": "exercise"})
            store.confirm_day(iso)
        elif n == 2:
            store.retime(iso, s("11:00"), s("12:30"), s("11:30"), s("13:00"), {"label": "Study", "category_id": "study"})

    # --- A few fake "Outlook" events (imported calendar) ---
    rows = []
    for i, (title, start, end, where) in enumerate([
        ("Chemistry 101", "09:00", "10:00", "Room 1.04"), ("Team stand-up", "10:00", "10:30", "Online"),
        ("Seminar: Design basics", "15:00", "16:00", "Hall B"),
    ]):
        for d in (0, 2, 4):
            day = (MONDAY + timedelta(days=d)).isoformat()
            if title == "Team stand-up" and d != 2:
                continue
            rows.append({"uid": f"demo-{i}-{d}", "date": day, "start": start, "end": end, "title": title,
                         "location": where, "all_day": 0, "exact": f"{start}–{end}",
                         "description": "Demo event (not a real calendar).",
                         "module_code": {"Chemistry 101": "CHEM101", "Seminar: Design basics": "DES110"}.get(title)})
    rows.append({"uid": "demo-holiday", "date": (MONDAY + timedelta(days=4)).isoformat(), "start": None,
                 "end": None, "title": "Bank holiday", "location": None, "all_day": 1, "exact": None,
                 "description": None})
    store.replace_outlook(rows)

    # --- Daily Log: the last 30 days of journal entries, with sleep tracked ---
    store.set_tracking(sleep=True)
    with store.db() as conn:
        for back in range(30):
            day = TODAY - timedelta(days=back)
            if random.random() < 0.1:
                continue                                # a few days not logged
            sleep = random.choice([6.0, 6.5, 7.0, 7.0, 7.5, 8.0, 8.5])
            store.save_entry(conn, day.isoformat(), random.choice(NOTES), sleep)

    # --- Deadlines: two for the modules (one with a plan), and one on its own with a time ---
    essay = store.add_deadline("Lab report", TODAY + timedelta(days=9), due_time="17:00", module_id=chem)
    store.add_deadline("Design brief", TODAY + timedelta(days=20), module_id=design)
    store.add_deadline("Renew passport", TODAY + timedelta(days=5))
    store.plan_deadline(essay, gr.get_module(chem)["category_id"], total=6)

    # --- Habits with streaks ---
    for name, rate in (("Read 20 pages", 0.8), ("Exercise", 0.6), ("Meditate", 0.5), ("No phone in bed", 0.4)):
        store.add_habit(name)
        habit_id = store.find_habit(name)[0]
        with store.db() as conn:
            for back in range(30):
                if back < 5 and name == "Read 20 pages" or random.random() < rate:   # a current streak
                    store.set_habit_done(conn, habit_id, (TODAY - timedelta(days=back)).isoformat(), True)

    # --- Earlier weeks: study planned but only partly done (follow-through), and guitar most evenings ---
    for week in range(2, 8):
        for d in range(5):
            day = (MONDAY - timedelta(weeks=week) + timedelta(days=d)).isoformat()
            store.paint(day, "plan", store.slot_of("11:00"), store.slot_of("12:30"), {"label": "Study", "category_id": "study"})
            if random.random() < 0.65:
                store.paint(day, "actual", store.slot_of("11:00"), store.slot_of("12:30"),
                            {"label": "Study", "category_id": "study"})
            if week <= 4 and d in (0, 2, 3):
                store.paint(day, "actual", store.slot_of("21:30"), store.slot_of("22:30"),
                            {"label": "Guitar", "category_id": "rest"})
        for d in range(7):                                  # those weeks were confirmed day by day
            store.mark_confirmed(MONDAY - timedelta(weeks=week) + timedelta(days=d))

    # --- Goals: two that count timetable hours, one counting a habit, one kept by hand ---
    store.add_goal("Study", "monthly", TODAY, 30, "h", category_id="study")
    store.add_goal("Side project", "monthly", TODAY, 25, "h", category_id="projects")
    store.add_goal("Learn Spanish", "monthly", TODAY, 300, "h", category_id="study", label="Spanish")   # can't be done in time
    store.add_goal("Exercise", "monthly", TODAY, 16, "sessions", habit_id=store.find_habit("Exercise")[0])
    books = store.add_goal("Read books", "yearly", TODAY, 20, "books")
    store.set_goal_progress(books["id"], 14)

    print(f"Demo data created in: {FOLDER}")
    print(f"Run the app on it:    VENATO_DATA_DIR='{FOLDER}' .venv/bin/streamlit run app.py")


if __name__ == "__main__":
    main()
