"""
The setup wizard's steps. A new install starts blank; setup only ever adds things, so running it again
never deletes anything. Every step but Welcome can be skipped, and "Skip setup" leaves the app as it is.

  Welcome -> Are you a student? -> (students: Uni timetable -> Canvas -> Your modules -> Study hours)
  -> Your goals -> What would you track? -> Your day -> Your first week -> Home

What a step writes happens when its Next is pressed, and writing again changes the same thing rather than
adding a second (goals made in this setup are remembered by id in st.session_state["ob"]).
settings_ui.wizard() draws the page; settings_ui._finish() turns on the core blocks.
"""

import re
from datetime import timedelta
from html import escape

import streamlit as st

from venato import feeds
from venato import home_layout as hl
from venato import outlook
from venato import pace
from venato import store
from venato import suggest
from venato.blocks import grades as gr
from venato.ui import kit

# (key, name, icon, only for students)
STEPS = [
    ("welcome", "Welcome", ":material/waving_hand:", False),
    ("student", "Are you a student?", ":material/school:", False),
    ("timetable", "Uni timetable", ":material/calendar_month:", True),
    ("canvas", "Canvas", ":material/assignment:", True),
    ("modules", "Your modules", ":material/menu_book:", True),
    ("hours", "Study hours", ":material/schedule:", True),
    ("goals", "Your goals", ":material/flag:", False),
    ("track", "What would you track?", ":material/checklist:", False),
    ("day", "Your day", ":material/view_day:", False),
    ("week", "Your first week", ":material/event_available:", False),
    ("home", "Home", ":material/home:", False),
]
GOAL_SLOTS = [("In 3 months", 3), ("In 6 months", 6), ("In 1 year", 12)]
TARGET_GRADES = {"First": 70.0, "2:1": 60.0, "2:2": 50.0}
STUDY_WEEKS = 12                       # a study goal runs this many weeks; its hours are the weekly hours times this
DEFAULT_CREDITS = 15
NEW_GROUP = "New group…"


# ---------------------------------------------------------------------------
# State and logic (no drawing)
# ---------------------------------------------------------------------------

def today():
    return store.local_today()


def _ob():
    """What this run of setup remembers between steps."""
    return st.session_state.setdefault("ob", {})


def restart():
    """Start setup from Welcome with nothing remembered."""
    st.session_state.pop("ob", None)
    st.session_state["wizard_step"] = 0


def is_student():
    ob = _ob()
    return bool(ob["student"] if "student" in ob else store.load_settings().get("student"))


def steps():
    """The steps for this person: [(key, name, icon)]. Students get the four uni steps."""
    student = is_student()
    return [(k, n, i) for k, n, i, uni in STEPS if student or not uni]


def months_on(day, months):
    """The same day `months` later (the last day of the month if it has no such day)."""
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    month += 1
    nxt = (day.replace(year=year + 1, month=1, day=1) if month == 12 else day.replace(year=year, month=month + 1, day=1))
    return day.replace(year=year, month=month, day=min(day.day, (nxt - timedelta(days=1)).day))


def check_feed(text, kind, fetcher=None, day=None):
    """
    Check a pasted link for the "uni" timetable or "canvas" step and download it once (fetcher is for tests).
    Returns outlook.try_link's {data, count, preview, kind} plus url, and for a timetable the lectures in the
    next 7 days and the modules found. Raises outlook.LinkError / outlook.SyncError with a message to show.
    """
    try:
        url, _ = outlook.check_link(text)                     # an Outlook link: .html is swapped for .ics
    except outlook.LinkError:
        url, _ = outlook.check_any_link(text)
    found = outlook.try_link(url, fetcher, day)
    is_canvas = found["kind"] == "canvas"
    if kind == "canvas" and not is_canvas:
        raise outlook.LinkError("That isn't a Canvas calendar feed. In Canvas, open Calendar and copy the "
                                "Calendar Feed link.")
    if kind == "uni" and is_canvas:
        raise outlook.LinkError("That's a Canvas link. Paste it on the Canvas step; this one is for your timetable.")
    found["url"] = url
    if kind == "uni":
        events = outlook.parse(found["data"], day)
        start = day or today()
        found["lectures"] = sum(1 for e in events if not e["all_day"] and start <= e["start"].date() < start + timedelta(days=7))
        found["modules"] = feeds.detect_modules(events)
    return found


def connect_feed(found, day=None):
    """Save a checked link (it stays in the system secret store) and import it: lectures go on the timetable,
    Canvas assignments become deadlines. Returns the sync's status."""
    status = outlook.add_calendar("Canvas" if found["kind"] == "canvas" else "Uni timetable",
                                  found["url"], found["data"], day)
    _forget_calendars()
    return status


def _forget_calendars():
    """A calendar was connected: what setup worked out from the old ones is stale."""
    ob = _ob()
    ob.pop("detected", None)
    ob.pop("canvas_events", None)


def detected_modules(day=None):
    """[{code, name, count}] found in the connected timetable calendars (Canvas has no module names).
    Parsed once per run of setup (kept in `ob`, cleared when a calendar is connected); `day` is for tests."""
    ob = _ob()
    if day is None and "detected" in ob:
        return ob["detected"]
    events = []
    for _, data in outlook.cached_calendars():
        if feeds.is_canvas("", data):
            continue
        try:
            events += outlook.parse(data, day)
        except Exception:                                      # a calendar that no longer parses adds nothing
            continue
    found = feeds.detect_modules(events)
    if day is None:
        ob["detected"] = found
    return found


def canvas_courses(day=None):
    """The connected Canvas courses: [{course_id, label, titles (a couple of its assignments), module_id}].
    The feeds are parsed once per run of setup (kept in `ob`); the module links are read fresh."""
    ob = _ob()
    if day is None and "canvas_events" in ob:
        events = ob["canvas_events"]
    else:
        events = []
        for _, data in outlook.cached_calendars():
            if feeds.is_canvas("", data):
                try:
                    events += feeds.canvas_events(data, store.tz())
                except Exception:
                    continue
        if day is None:
            ob["canvas_events"] = events
    linked = {c["course_id"]: c["module_id"] for c in gr.canvas_courses()}
    return [{"course_id": c["course_id"], "label": c["label"], "module_id": linked.get(c["course_id"]),
             "titles": [e["title"] for e in events if e.get("course_id") == c["course_id"]][:2]}
            for c in feeds.canvas_courses(events)]


def _module_for(code, name):
    """The module already in Venato for a detected one (same code, else same name), or None."""
    for m in gr.modules():
        if code and m["code"] and feeds.norm_code(m["code"]) == code:
            return m
        if m["name"].lower() == str(name or "").lower():
            return m
    return None


def add_modules(picked, credits=DEFAULT_CREDITS, target=None):
    """Add the picked modules ([{code, name}]): each gets its own timetable category. One already in Venato is
    left alone. Returns the ids of the ones just made."""
    made = []
    for m in picked:
        if _module_for(m.get("code"), m["name"]):
            continue
        made.append(gr.add_module(m["name"], credits, target=target, code=m.get("code")))
    return made


def link_courses(links):
    """{course_id: module name or None}: link each Canvas course to the module of that name."""
    by_name = {m["name"].lower(): m["id"] for m in gr.modules()}
    current = {c["course_id"]: c["module_id"] for c in gr.canvas_courses()}
    for course_id, name in links.items():
        mid = by_name.get(str(name or "").lower())
        if mid != current.get(course_id):
            gr.link_canvas_course(course_id, mid)


def apply_study_hours(per_week, day=None):
    """The default hours a week for every module, and one hours goal for each module that has none yet
    (counting its category, which also holds its lectures). A module's own number (its page) wins."""
    day = day or today()
    store.save_settings(study_hours=float(per_week))
    made = []
    if per_week <= 0:
        return made
    have = {g["category_id"] for g in store.goals_open(day) if g["category_id"] and g["unit"] == "h" and not g["deadline_id"]}
    for m in gr.modules():
        cid = m["category_id"] or gr.create_category(m["id"])
        if cid in have:
            continue
        hours = gr.week_hours_goal(m)
        if hours > 0:
            made.append(store.add_goal(f"{m['name']} study", None, day, hours * STUDY_WEEKS, unit="h", category_id=cid,
                                       due=day + timedelta(weeks=STUDY_WEEKS)))
    return made


def save_goals(rows, day=None):
    """
    rows: [(text, number or None, months)] in the order of GOAL_SLOTS. Each filled one is a goal due in that
    many months (without a number, a goal of 1 to tick off). Saving again changes the goal this setup made
    for that row; a row emptied removes only that goal. Returns {row: goal id}.
    """
    day = day or today()
    ids = _ob().setdefault("goal_ids", {})
    for i, (text, number, months) in enumerate(rows):
        text, gid = (text or "").strip(), ids.get(i)
        if gid and not store.get_goal(gid):
            gid = ids.pop(i, None)
        if not text:
            if gid:
                store.delete_goal(gid)
                ids.pop(i, None)
            continue
        target = float(number) if number and number > 0 else 1.0
        if gid:
            store.update_goal(gid, title=text, target=target, due=months_on(day, months))
        else:
            ids[i] = store.add_goal(text, None, day, target, due=months_on(day, months))["id"]
        _ob().setdefault("goal_nums", {})[i] = bool(number and number > 0)
    return dict(ids)


def ensure_category(cid):
    """Make one of the example categories (and the activity names that default to it) if it isn't there yet."""
    if cid in set(store.load_categories()["id"]):
        return
    for ex_id, name, colour, text, grp in store.EXAMPLE_CATEGORIES:
        if ex_id == cid:
            store.save_category(ex_id, name, colour, grp, text)
            for label, target in store.EXAMPLE_LABEL_MAP.items():
                if target == cid and not any(r["label"].lower() == label.lower() for r in store.load_label_map().to_dict("records")):
                    store.set_label_default(label, cid)


def apply_suggestion(s, goal_id=None, number=False):
    """Switch on one suggestion from suggest.for_goal and link it to its goal. A goal counts a habit's ticks or
    timetable hours, never both: a habit wins, and a category links only for a goal with a number (read as hours)."""
    kind = s["kind"]
    if kind == "habit":
        store.add_habit(s["name"])
        if goal_id:                                   # the goal counts ticks now: no category, and no hours unit
            goal = store.get_goal(goal_id)
            store.update_goal(goal_id, habit_id=store.find_habit(s["name"])[0],
                              **({"unit": None} if goal and goal["category_id"] and goal["unit"] == "h" else {}))
    elif kind == "category":
        ensure_category(s["cid"])
        goal = store.get_goal(goal_id) if goal_id else None
        if goal and number and goal["habit_id"] is None:
            store.update_goal(goal_id, category_id=s["cid"], unit="h")
    elif kind in ("sleep", "water"):
        store.set_tracking(**{kind: True})


def add_category(name, colour, group):
    """Add a category of the student's own (name, colour, group: made if new). Returns its id."""
    name, group = (name or "").strip(), (group or "").strip()
    if not name or not group:
        raise ValueError("Give the category a name and a group.")
    if any(n.lower() == name.lower() for n in store.load_categories()["name"]):
        raise ValueError(f"There's already a category called {name}.")
    taken = set(store.load_categories()["id"])
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "category"
    cid, n = base, 2
    while cid in taken:
        cid, n = f"{base}-{n}", n + 1
    store.save_category(cid, name, colour, group)
    return cid


def first_week(day=None, ctx=None):
    """The sittings Plan my goals would add in the next 7 days: goal_time.suggestions_for, oldest first."""
    from venato.ui import goal_time
    ctx = ctx or pace.Ctx()
    day = day or ctx.today
    out = []
    for first in (pace.week_days(day)[0], pace.week_days(day)[0] + timedelta(days=7)):
        out += [s for s in goal_time.suggestions_for(first, ctx) if day.isoformat() <= s["date"] < (day + timedelta(days=7)).isoformat()]
    return sorted(out, key=lambda s: (s["date"], s["start"]))


def add_first_week(sittings):
    """Add the suggested sittings to the Plan (only into free time; nothing is overwritten). Returns how many went in."""
    from venato.ui import goal_time
    return sum(goal_time.add_suggestion(s["date"], s["start"], s["end"],
                                        {"label": s["label"], "category_id": s["categoryId"], "details": None})
               for s in sittings)


def home_picks():
    """The Home widgets this setup suggests: [(key, name)], only ones that make sense from what was picked."""
    picks = [("modules", "Modules")] if is_student() else []
    if store.deadlines():
        picks.append(("deadlines", "Deadlines"))
    if store.get_habits():
        picks.append(("habits", "Habits"))
    if store.goals_open():
        picks.append(("goals", "Goals"))
    return picks


def chosen_home_keys():
    return [k for k, _ in home_picks() if st.session_state.get(f"ob_home_{k}", False)]


def prefill_home(keys):
    """Put these widgets on Home if they aren't there (the blocks must be on: setup's _finish does that first).
    Nothing is moved or hidden."""
    from venato.ui import home
    cat = home.catalog()
    sizes = {k: w.size for k, w in cat.items()}
    raw = store.load_settings().get("home")
    cells = hl.normalise(raw, sizes)
    new = cells
    for key in keys:
        if key in cat:
            new = hl.add(new, key, cat[key].size)
    if new != cells:
        store.save_settings(home=hl.keep_unavailable(raw, new, sizes))


# ---------------------------------------------------------------------------
# Steps: drawing, and what Next saves
# ---------------------------------------------------------------------------

def _welcome():
    from venato import system
    st.title("Welcome to Venato", anchor=False)
    st.markdown(
        "Venato keeps track of your days:\n\n"
        "- :material/calendar_view_week: a **timetable** of what you planned and what you actually did\n"
        "- :material/checklist: **to-dos** and **deadlines**, and **goals** with a pace to keep\n"
        "- :material/timer: **focus** sessions and a **weekly review** to see how it went\n\n"
        f":material/lock: **Your data stays on your {system.COMPUTER}.** Nothing is uploaded.\n\n"
        "Setup takes about two minutes and you can skip any step. **Skip setup** leaves Venato blank, ready for "
        "you to add things yourself.")


def _student():
    st.header("Are you a student?", anchor=False)
    st.markdown("Students get a **Modules** page and a few extra steps: your uni timetable, Canvas deadlines "
                "and study hours.")
    now = _ob().get("student", store.load_settings().get("student"))
    st.radio("Are you a student?", ["Yes", "No"], index=None if now is None else 0 if now else 1,
             key="ob_student", horizontal=True, label_visibility="collapsed")


def _save_student():
    answer = st.session_state.get("ob_student")
    if answer:
        _ob()["student"] = answer == "Yes"
        store.save_settings(student=answer == "Yes")


GUIDES = {
    "uni": ("1. Open your university's Outlook calendar on the web (outlook.office.com).\n"
            "2. **Settings** → **Calendar** → **Shared calendars** → **Publish a calendar**.\n"
            "3. Pick your timetable calendar, choose **Can view all details**, and press **Publish**.\n"
            "4. Copy the **ICS** link and paste it below."),
    "canvas": ("1. Open Canvas and go to **Calendar**.\n"
               "2. On the right, press **Calendar Feed**.\n"
               "3. Copy the link and paste it below."),
}


def _link_step(kind):
    ob = _ob()
    if kind == "uni":
        st.header("Your uni timetable", anchor=False)
        st.markdown("Your lectures appear in the timetable, and Venato finds your modules from them. Venato only reads it.")
    else:
        st.header("Canvas", anchor=False)
        st.markdown("Your Canvas assignments become deadlines. Venato only reads the feed.")
    st.markdown(GUIDES[kind])
    st.info("Anyone with this link can see your calendar. Venato keeps it in your system's secret store, never in a file.",
            icon=":material/visibility:")
    with st.form(f"ob_form_{kind}", clear_on_submit=True, border=False):
        text = st.text_input("Calendar link", type="password", key=f"ob_link_{kind}", placeholder="https://…",
                             help="Hidden so the link isn't shown on screen.")
        go = st.form_submit_button("Connect", type="primary", icon=":material/link:")
    if go:
        try:
            with st.spinner("Checking the link…"):
                found = check_feed(text, kind)
                connect_feed(found)
            ob[f"found_{kind}"] = found
        except outlook.AlreadyAdded:
            st.info("Already connected. Nothing more to do here.", icon=":material/check_circle:")
        except outlook.LinkError as e:
            st.error(str(e), icon=":material/error:")
        except outlook.SyncError as e:
            st.error(outlook.friendly(e).replace("Outlook", "the calendar"), icon=":material/error:")
        except Exception as e:
            st.error(f"That link didn't give a calendar Venato can read ({type(e).__name__}).", icon=":material/error:")
    found = ob.get(f"found_{kind}")
    if found:
        if kind == "uni":
            n, mods = found["lectures"], len(found["modules"])
            st.success(f"Connected. Found {n} lecture{'s' if n != 1 else ''} next week"
                       + (f" and {mods} module{'s' if mods != 1 else ''}." if mods else "."), icon=":material/check_circle:")
        else:
            st.success(f"Connected. {outlook.found_text(found)}", icon=":material/check_circle:")
        for ev in found["preview"]:
            st.markdown(f"- **{escape(ev['title'])}** · {ev['when']}")
    elif outlook.cached_calendars():
        st.caption("A calendar is already connected. Paste another link to add one.")


def _cand_key(c):
    """A detected module's widget key: its code, else its name (so it doesn't shift when others are added)."""
    return c["code"] or c["name"].lower()


def _modules():
    ob = _ob()
    st.header("Your modules", anchor=False)
    st.markdown("Tick the ones to add and rename any you like. Each gets its own category in the timetable.")
    existing = gr.modules()
    cands = [c for c in detected_modules() if not _module_for(c["code"], c["name"])]
    ob["cands"] = cands
    for m in existing:
        st.markdown(f":material/check_circle: **{escape(m['name'])}**" + (f" · {escape(m['code'])}" if m["code"] else "")
                    + " · :gray[already in Venato]")
    names = [m["name"] for m in existing]
    for c in cands:
        keep, name = st.columns([1, 5], vertical_alignment="bottom")
        on = keep.checkbox("Add", value=True, key=f"ob_keep_{_cand_key(c)}")
        typed = name.text_input(c["code"] or "Module", value=c["name"], key=f"ob_name_{_cand_key(c)}",
                                help=f"{c['count']} events in your timetable")
        if on and typed.strip():
            names.append(typed.strip())
    if not cands and not existing:
        kit.empty("No modules found yet. Add them below, or connect your timetable on the earlier step.", ":material/info:")
    a, b = st.columns(2)
    a.number_input("Credits for each new module", 1, 200, DEFAULT_CREDITS, key="ob_credits",
                   help="You can change a module's credits later on the Modules page.")
    b.segmented_control("Target grade", list(TARGET_GRADES), key="ob_target",
                        help="Your target for every new module. You can change it for each one later.")
    with st.form("ob_add_module", clear_on_submit=True, border=False):
        x, y = st.columns([4, 1], vertical_alignment="bottom")
        new = x.text_input("Add a module", placeholder="e.g. Organic Chemistry")
        if y.form_submit_button("Add", icon=":material/add:") and new.strip():
            try:
                add_modules([{"name": new.strip()}], st.session_state.get("ob_credits") or DEFAULT_CREDITS,
                            TARGET_GRADES.get(st.session_state.get("ob_target")))
                st.rerun()
            except gr.GradeError as e:
                st.error(str(e), icon=":material/error:")
    courses = canvas_courses()
    if courses:
        st.subheader("Your Canvas courses", anchor=False)
        st.caption("Canvas doesn't name its courses. Link each to one of your modules, or leave it unlinked: its "
                   "deadlines still come in, just without a module.")
        for c in courses:
            current = next((m["name"] for m in existing if m["id"] == c["module_id"]), None)
            options = ["Not linked"] + sorted(dict.fromkeys(names))
            what = ", ".join(c["titles"]) or "no assignments yet"
            st.selectbox(f"[{c['label'] or c['course_id']}] {what}", options, key=f"ob_course_{c['course_id']}",
                         index=options.index(current) if current in options else 0)


def _save_modules():
    ob = _ob()
    picked = []
    for c in ob.get("cands", []):
        name = (st.session_state.get(f"ob_name_{_cand_key(c)}") or c["name"]).strip()
        if st.session_state.get(f"ob_keep_{_cand_key(c)}", True) and name:
            picked.append({"code": c["code"], "name": name})
    add_modules(picked, st.session_state.get("ob_credits") or DEFAULT_CREDITS,
                TARGET_GRADES.get(st.session_state.get("ob_target")))
    links = {}
    for c in canvas_courses():
        choice = st.session_state.get(f"ob_course_{c['course_id']}")
        if choice is not None:
            links[c["course_id"]] = None if choice == "Not linked" else choice
    link_courses(links)


def _hours():
    st.header("Study hours", anchor=False)
    mods = gr.modules()
    st.markdown("How many hours a week do you want to spend on each module? Lectures count too. "
                "You can change it for one module on its page.")
    st.slider("Hours a week for each module", 0.0, 20.0, float(store.load_settings().get("study_hours", gr.DEFAULT_WEEK_HOURS)),
              0.5, key="ob_hours")
    if mods:
        st.caption(f"Each of your {len(mods)} module{'s' if len(mods) != 1 else ''} gets a goal for the next "
                   f"{STUDY_WEEKS} weeks.")
    else:
        kit.empty("You haven't added a module yet, so there's nothing to set. The hours are kept for when you do.",
                  ":material/info:")


def _save_hours():
    apply_study_hours(st.session_state.get("ob_hours", gr.DEFAULT_WEEK_HOURS))


def _goal_row(i, label):
    ob = _ob()
    gid = ob.get("goal_ids", {}).get(i)
    goal = store.get_goal(gid) if gid else None
    a, b = st.columns([4, 1], vertical_alignment="bottom")
    a.text_input(label, value=goal["title"] if goal else "", key=f"ob_goal_{i}", placeholder="e.g. Get a First")
    b.number_input("Number", 0.0, 100000.0, float(goal["target"]) if goal and ob.get("goal_nums", {}).get(i) else None,
                   key=f"ob_goal_n_{i}", placeholder="optional", help="A number to reach, like 100 for 100 hours. "
                   "Leave it empty for a goal you just tick off.", label_visibility="collapsed")


def _goals():
    st.header("Your goals", anchor=False)
    st.markdown("What do you want to have done in 3 months, 6 months and a year? A few words is enough, "
                "and a number if there is one.")
    for i, (label, _) in enumerate(GOAL_SLOTS):
        _goal_row(i, label)
    targets = [m for m in gr.modules() if m["target"] is not None]
    if is_student() and targets:
        kit.subhead("Goals you already have")
        for m in targets:
            st.markdown(f":material/flag: {escape(m['name'])}: {m['target']:g}%")


def _save_goals():
    save_goals([(st.session_state.get(f"ob_goal_{i}"), st.session_state.get(f"ob_goal_n_{i}"), months)
                for i, (_, months) in enumerate(GOAL_SLOTS)])


def _my_goals():
    """[(row, goal)] of the goals this setup made."""
    return [(i, g) for i, gid in sorted(_ob().get("goal_ids", {}).items()) if (g := store.get_goal(gid))]


def _suggestion_label(s):
    return {"habit": f"A habit to tick: {s['name']}", "category": f"A timetable category: {s['name']}",
            "sleep": "Log my sleep in the Daily Log", "water": "Log my water in the Daily Log"}[s["kind"]]


def _track():
    ob = _ob()
    st.header("What would you track?", anchor=False)
    st.markdown("These are examples based on your goals: pick what you want. Nothing is switched on until you tick it.")
    goals = _my_goals()
    if not goals:
        kit.empty("Add a goal on the previous step and examples show up here.", ":material/info:")
    for i, g in goals:
        found = suggest.for_goal(g["title"])
        kit.subhead(g['title'])
        if not found:
            st.caption("No examples for this one. Add your own below.")
        for j, s in enumerate(found):
            st.checkbox(_suggestion_label(s), value=False, key=f"ob_sg_{i}_{j}")
    for name, _ in ob.get("own", []):
        st.markdown(f":material/check: Your own habit: **{escape(name)}**")
    with st.form("ob_own", clear_on_submit=True, border=False):
        a, b, c = st.columns([3, 3, 1], vertical_alignment="bottom")
        name = a.text_input("Add your own habit", placeholder="e.g. Stretch")
        titles = ["No goal"] + [g["title"] for _, g in goals]
        link = b.selectbox("Count it towards", titles)
        if c.form_submit_button("Add", icon=":material/add:") and name.strip():
            ob.setdefault("own", []).append((name.strip(), None if link == "No goal" else link))
            st.rerun()


def _save_track():
    ob = _ob()
    goals = _my_goals()
    for i, g in goals:
        for j, s in enumerate(suggest.for_goal(g["title"])):
            if st.session_state.get(f"ob_sg_{i}_{j}"):
                apply_suggestion(s, g["id"], ob.get("goal_nums", {}).get(i, False))
    for name, goal_title in ob.get("own", []):
        gid = next((g["id"] for _, g in goals if g["title"] == goal_title), None)
        apply_suggestion({"kind": "habit", "name": name}, gid)
    ob["own"] = []


def _text_on(colour):
    """Black or white text, whichever reads better on a #RRGGBB colour."""
    r, g, b = (int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    lum = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    return "#000000" if (lum + 0.05) / 0.05 >= 1.05 / (lum + 0.05) else "#FFFFFF"


def _chip(name, colour):
    colour = colour if re.fullmatch(r"#[0-9A-Fa-f]{6}", str(colour)) else "#999999"
    return (f'<span style="display:inline-block;margin:.15rem .3rem .15rem 0;padding:.15rem .65rem;border-radius:1rem;'
            f'background:{colour};color:{_text_on(colour)};font-size:.9rem">{escape(name)}</span>')


def _add_own_category():
    group = st.session_state.get("ob_cat_group")
    group = st.session_state.get("ob_cat_newgroup") if group in (None, NEW_GROUP) else group
    try:
        add_category(st.session_state.get("ob_cat_name"), st.session_state.get("ob_cat_colour") or "#4E79A7", group)
        st.session_state["ob_cat_name"] = ""
    except ValueError as e:
        st.session_state["ob_error"] = str(e)


def _day():
    st.header("Your day", anchor=False)
    st.markdown("Categories colour your timetable. Your modules and anything you picked are already there. "
                "Tick any examples you'd like, or add your own.")
    cats = store.load_categories()
    if cats.empty:
        kit.empty("No categories yet.", ":material/info:")
    for grp in dict.fromkeys(cats["grp"]):
        rows = cats[cats["grp"] == grp]
        kit.subhead(grp)
        st.html("".join(_chip(r["name"], r["colour"]) for r in rows.to_dict("records")))
    have = set(cats["id"]) | {n.lower() for n in cats["name"]}
    examples = [e for e in store.EXAMPLE_CATEGORIES if e[0] not in have and e[1].lower() not in have]
    if examples:
        kit.subhead("Examples: pick what you want")
        cols = st.columns(3)
        for i, (cid, name, colour, _, grp) in enumerate(examples):
            cols[i % 3].checkbox(f"{name} ({grp})", value=False, key=f"ob_ex_{cid}")
    kit.subhead("Add your own")
    a, b = st.columns([3, 1], vertical_alignment="bottom")
    a.text_input("Name", key="ob_cat_name", placeholder="e.g. Lab work")
    b.color_picker("Colour", "#4E79A7", key="ob_cat_colour")
    groups = store.groups()
    c, d = st.columns(2, vertical_alignment="bottom")
    group = c.selectbox("Group", groups + [NEW_GROUP], key="ob_cat_group")
    if group == NEW_GROUP:
        d.text_input("New group name", value="Life", key="ob_cat_newgroup")
    st.button("Add category", key="ob_cat_add", icon=":material/add:", on_click=_add_own_category)


def _save_day():
    for cid, *_ in store.EXAMPLE_CATEGORIES:
        if st.session_state.get(f"ob_ex_{cid}"):
            ensure_category(cid)


def _grid(sittings):
    cats = {r["id"]: r["colour"] for r in store.load_categories().to_dict("records")}
    from venato import regional
    days = []
    for d in dict.fromkeys(s["date"] for s in sittings):
        items = "".join(
            f'<div class="ob-sit" style="border-left-color:{cats.get(s["categoryId"], "#999999")}">'
            f'{regional.time_range(s["start"], s["end"])}<br>{escape(s["label"])}</div>'
            for s in sittings if s["date"] == d)
        days.append(f'<div><b>{regional.day_month(d)}</b>{items}</div>')
    st.html("<style>.ob-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:.6rem}"
            ".ob-sit{border-left:4px solid;padding:.2rem .45rem;margin-top:.3rem;font-size:.85rem;"
            "background:rgba(128,128,128,.14)}</style>"
            f'<div class="ob-grid">{"".join(days)}</div>')


def _add_week():
    added = add_first_week(_ob().get("sittings", []))
    st.session_state["ob_added"] = added
    st.session_state["wizard_step"] = st.session_state.get("wizard_step", 0) + 1


def _week():
    ob = _ob()
    st.header("Your first week", anchor=False)
    sittings = first_week()
    ob["sittings"] = sittings
    if not sittings:
        kit.empty("Nothing to suggest yet. Hours goals, like a module's study time, get sittings here, in your free time.",
                  ":material/info:")
        return
    hours = sum(store.slot_of(s["end"]) - store.slot_of(s["start"]) for s in sittings) / 2
    st.markdown(f"Here's how your goals could fit in the next 7 days: {pace.fmt(hours)} h in free time. "
                "Nothing already in your timetable moves.")
    _grid(sittings)
    st.button("Add to my Plan", key="ob_week_add", type="primary", icon=":material/playlist_add:", on_click=_add_week)


def _home():
    st.header("Home", anchor=False)
    picks = home_picks()
    st.markdown("Home shows what you want to see first. These are added from what you picked:")
    if not picks:
        kit.empty("Nothing extra yet. Home starts with your timetable, to-dos and what needs you.", ":material/info:")
    for key, name in picks:
        st.checkbox(f"Show {name} on Home", value=True, key=f"ob_home_{key}")
    st.caption("Press **Arrange** at the top of Home to move, resize or hide anything.")


STEP_BODY = {"student": _student, "modules": _modules, "hours": _hours, "goals": _goals, "track": _track, "day": _day,
             "week": _week, "home": _home}
SAVE = {"student": _save_student, "modules": _save_modules, "hours": _save_hours, "goals": _save_goals,
        "track": _save_track, "day": _save_day}


def _go(index, save=None):
    """Move to a step, first saving the one we're leaving (Next); an error stays on it."""
    if save:
        try:
            SAVE[save]()
        except ValueError as e:
            st.session_state["ob_error"] = str(e)
            return
    st.session_state["wizard_step"] = index


def wizard(finish):
    """The full-screen setup: no sidebar. `finish` is called when it's done or skipped."""
    st.html("<style>[data-testid='stSidebar'], [data-testid='stSidebarCollapsedControl'] { display: none; }</style>")
    listed = steps()
    step = min(st.session_state.setdefault("wizard_step", 0), len(listed) - 1)
    key = listed[step][0]
    _, mid, _ = st.columns([1, 3, 1])
    with mid:
        st.caption(f"Setup · step {step + 1} of {len(listed)}")
        st.progress((step + 1) / len(listed))
        if error := st.session_state.pop("ob_error", None):
            st.error(error, icon=":material/error:")
        if key == "welcome":
            _welcome()
        elif key in ("timetable", "canvas"):
            _link_step("uni" if key == "timetable" else "canvas")
        else:
            STEP_BODY[key]()
        st.divider()
        back, skip, nxt = st.columns([1, 1, 1])
        last = step == len(listed) - 1
        if step > 0:
            back.button("Back", key="wiz_back", on_click=_go, args=(step - 1,), icon=":material/arrow_back:")
        if last:
            nxt.button("Start using Venato", key="wiz_finish", type="primary", on_click=finish, width="stretch")
        elif key == "welcome":
            skip.button("Skip setup", key="wiz_skip_all", on_click=finish)
            nxt.button("Get started", key="wiz_next", type="primary", on_click=_go, args=(step + 1,),
                       width="stretch", icon=":material/arrow_forward:")
        else:
            skip.button("Skip for now", key="wiz_skip", on_click=_go, args=(step + 1,))
            nxt.button("Next", key="wiz_next", type="primary", on_click=_go, args=(step + 1, key if key in SAVE else None),
                       width="stretch", icon=":material/arrow_forward:")
