"""
The setup wizard's steps. A new install starts blank; setup only ever adds things, so running it again
never deletes anything. Every step but Welcome can be skipped, and "Skip setup" leaves the app as it is.

  Welcome (are you a student?) -> (students: Connect your calendars -> Your modules, with their study hours)
  -> Your goals -> What would you track? (and the timetable colours) -> Your first week

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
    ("calendars", "Calendars", ":material/calendar_month:", True),
    ("modules", "Modules", ":material/menu_book:", True),
    ("goals", "Goals", ":material/flag:", False),
    ("track", "Track", ":material/checklist:", False),
    ("week", "First week", ":material/event_available:", False),
]
GOAL_SLOTS = [("In 3 months", 3), ("In 6 months", 6), ("In 1 year", 12)]
STUDY_WEEKS = 12                       # a study goal runs this many weeks; its hours are the weekly hours times this
DEFAULT_CREDITS = 15


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
    """The steps for this person: [(key, name, icon)]. Students get the two uni steps."""
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


def add_modules(picked):
    """Add the picked modules ([{code, name}]): each gets its own timetable category, the default credits and no
    target (setup asks no grade questions). One already in Venato is left alone. Returns the ids of the ones just made."""
    made = []
    for m in picked:
        if _module_for(m.get("code"), m["name"]):
            continue
        made.append(gr.add_module(m["name"], DEFAULT_CREDITS, code=m.get("code")))
    _ob().setdefault("new_modules", []).extend(made)           # the only ones the study goals touch
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
    """The default hours a week, and one hours goal for each module made in this run of setup that has none yet
    (counting its category, which also holds its lectures). A module's own number (its page) wins. Modules
    from before, and ones without a category, are left alone."""
    day = day or today()
    store.save_settings(study_hours=float(per_week))
    made = []
    if per_week <= 0:
        return made
    have = {g["category_id"] for g in store.goals_open(day) if g["category_id"] and g["unit"] == "h" and not g["deadline_id"]}
    mine = set(_ob().get("new_modules", []))
    for m in gr.modules():
        cid = m["category_id"]
        if m["id"] not in mine or not cid or cid in have:
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
    cats = store.load_categories()
    if cid in set(cats["id"]):
        return
    for ex_id, name, colour, text, grp in store.EXAMPLE_CATEGORIES:
        if ex_id == cid:
            if name.lower() in {n.lower() for n in cats["name"]}:      # already there under another id
                return
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


def default_group():
    """The group an own category goes in: the one with the fewest categories (not Modules), else Life."""
    cats = store.load_categories()
    counts = cats[cats["grp"] != store.MODULES_GROUP]["grp"].value_counts()
    counts = counts.reindex([g for g in store.groups() if g in counts.index])
    return counts.idxmin() if len(counts) else "Life"


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
        "Setup takes a few minutes and you can skip any step. **Skip setup** leaves Venato blank, ready for "
        "you to add things yourself.")
    st.subheader("Are you a student?", anchor=False)
    st.markdown("Students get a **Modules** page and a few extra steps: your uni timetable, Canvas deadlines "
                "and study hours.")
    ob = _ob()
    saved = ob["student"] if "student" in ob else store.load_settings().get("student")
    yes, no = st.columns(2)
    yes.button("I'm at uni", key="ob_student_yes", type="primary" if saved is True else "secondary",
               icon=":material/school:", width="stretch", on_click=_answer_student, args=(True,))
    no.button("Not a student", key="ob_student_no", type="primary" if saved is False else "secondary",
              icon=":material/person:", width="stretch", on_click=_answer_student, args=(False,))


def _save_student(answer):
    _ob()["student"] = answer
    store.save_settings(student=answer)


def _answer_student(answer):
    """Save the answer and go on to the next step (the list of steps depends on it)."""
    _save_student(answer)
    st.session_state["wizard_step"] = st.session_state.get("wizard_step", 0) + 1


GUIDES = {
    "uni": ("1. Open your university's Outlook calendar on the web (outlook.office.com).\n"
            "2. **Settings** → **Calendar** → **Shared calendars** → **Publish a calendar**.\n"
            "3. Pick your timetable calendar, choose **Can view all details**, and press **Publish**.\n"
            "4. Copy the **ICS** link and paste it below."),
    "canvas": ("1. Open Canvas and go to **Calendar**.\n"
               "2. On the right, press **Calendar Feed**.\n"
               "3. Copy the link and paste it below."),
}


def _connect_link(kind):
    """Connect the link typed in the box (nothing if it's empty). Returns "connected", "already" or None.
    Raises ValueError with a message to show when the link is no good."""
    text = (st.session_state.get(f"ob_link_{kind}") or "").strip()
    if not text:
        return None
    try:
        with st.spinner("Checking the link…"):
            found = check_feed(text, kind)
            connect_feed(found)
    except outlook.AlreadyAdded:
        return "already"
    except outlook.LinkError as e:
        raise ValueError(str(e))
    except outlook.SyncError as e:
        raise ValueError(outlook.friendly(e).replace("Outlook", "the calendar"))
    except Exception as e:
        raise ValueError(f"That link didn't give a calendar Venato can read ({type(e).__name__}).")
    _ob()[f"found_{kind}"] = found
    return "connected"


def _connect_button(kind):
    """The Connect button: the same as Next, but it stays on the step."""
    try:
        result = _connect_link(kind)
    except ValueError as e:
        st.session_state["ob_error"] = str(e)
        return
    if result == "already":
        _ob()[f"link_note_{kind}"] = "Already connected. Nothing more to do here."
    if result:
        st.session_state[f"ob_link_{kind}"] = ""


def _save_calendars():
    """Connect whatever is typed in either box. Both are tried; if either link is no good the step stays."""
    problems = []
    for kind in ("uni", "canvas"):
        try:
            if _connect_link(kind):
                st.session_state[f"ob_link_{kind}"] = ""
        except ValueError as e:
            problems.append(str(e))
    if problems:
        raise ValueError(" ".join(problems))


def _calendars():
    st.header("Connect your calendars", anchor=False)
    st.markdown("Both are optional. Venato only reads them.")
    st.info("Anyone with a calendar link can see that calendar. Venato keeps yours in your system's secret store, "
            "never in a file.", icon=":material/visibility:")
    for kind in ("uni", "canvas"):
        with st.container(border=True):
            _link_card(kind)


def _link_card(kind):
    ob = _ob()
    if kind == "uni":
        st.subheader("Uni timetable", anchor=False)
        st.markdown("Your lectures appear in the timetable, and Venato finds your modules from them.")
    else:
        st.subheader("Canvas", anchor=False)
        st.markdown("Your Canvas assignments become deadlines.")
    st.markdown(GUIDES[kind])
    if kind == "uni":
        with st.expander("Not using Outlook?"):
            st.markdown("- **Google Calendar** gives you a link in Settings → your calendar → "
                        "**Secret address in iCal format**.\n"
                        "- Other uni timetable sites usually have a **Subscribe** or **iCal/ICS** link.\n"
                        "- Paste any link that ends in **.ics**.")
    st.text_input("Calendar link", key=f"ob_link_{kind}", placeholder="https://…")
    st.button("Connect", key=f"ob_connect_{kind}", type="primary", icon=":material/link:",
              on_click=_connect_button, args=(kind,))
    if note := ob.pop(f"link_note_{kind}", None):
        st.info(note, icon=":material/check_circle:")
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
    x, y = st.columns([4, 1], vertical_alignment="bottom")
    x.text_input("Add a module", key="ob_new_module", placeholder="e.g. Organic Chemistry")
    y.button("Add", key="ob_add_module", icon=":material/add:", on_click=_add_module_button)
    _hours_boxes(existing, cands)
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


def _default_hours():
    return float(store.load_settings().get("study_hours", gr.DEFAULT_WEEK_HOURS))


def _hours_key(c=None, m=None):
    return f"ob_hours_{_cand_key(c)}" if c is not None else f"ob_hours_{m['id']}"


def _hours_boxes(existing, cands):
    """One hours-a-week box per module that will exist after Next, and what they add up to."""
    ob = _ob()
    start, total = {}, 0.0
    ob["hours_start"] = start
    rows = [(m["name"], _hours_key(m=m), min(gr.week_hours_goal(m), 80.0)) for m in existing]
    for c in cands:
        name = (st.session_state.get(f"ob_name_{_cand_key(c)}") or c["name"]).strip()
        if st.session_state.get(f"ob_keep_{_cand_key(c)}", True) and name:
            rows.append((name, _hours_key(c), min(_default_hours(), 80.0)))
    if not rows:
        return
    kit.subhead("Hours a week")
    for name, key, value in rows:
        start[key] = value
        total += st.number_input(name, 0.0, 80.0, value, 0.5, key=key, help="Lectures count too. You can change it "
                                 "for one module on its page.")
    st.caption(f"{len(rows)} module{'s' if len(rows) != 1 else ''} · {pace.fmt(total)} h a week, lectures included")


def _add_typed_module():
    """Add the module typed in the box (the Add button, and Next). Raises ValueError if it can't be added."""
    name = (st.session_state.get("ob_new_module") or "").strip()
    if not name:
        return
    add_modules([{"name": name}])
    st.session_state["ob_new_module"] = ""


def _add_module_button():
    try:
        _add_typed_module()
    except ValueError as e:
        st.session_state["ob_error"] = str(e)


def _save_modules():
    """Add the modules, set the hours boxes that were changed, then give the new modules their study goals."""
    ob, ss = _ob(), st.session_state
    start = ob.get("hours_start", {})
    _add_typed_module()
    for m in gr.modules():                                     # one from before: its box, if it was drawn and changed
        key = _hours_key(m=m)
        if key in ss and key in start and float(ss[key]) != start[key]:
            gr.set_week_hours_goal(m["id"], ss[key])
    default = _default_hours()
    for c in ob.get("cands", []):
        name = (ss.get(f"ob_name_{_cand_key(c)}") or c["name"]).strip()
        if ss.get(f"ob_keep_{_cand_key(c)}", True) and name:
            add_modules([{"code": c["code"], "name": name}])
            key = _hours_key(c)
            if key in ss and float(ss[key]) != default and (m := _module_for(c["code"], name)):
                gr.set_week_hours_goal(m["id"], ss[key])
    links = {}
    for c in canvas_courses():
        choice = st.session_state.get(f"ob_course_{c['course_id']}")
        if choice is not None:
            links[c["course_id"]] = None if choice == "Not linked" else choice
    link_courses(links)
    apply_study_hours(default)


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
    a, b, c = st.columns([3, 3, 1], vertical_alignment="bottom")
    a.text_input("Add your own habit", key="ob_own_name", placeholder="e.g. Stretch")
    a_titles = ["No goal"] + [g["title"] for _, g in goals]
    b.selectbox("Count it towards", a_titles, key="ob_own_link")
    c.button("Add", key="ob_own_add", icon=":material/add:", on_click=_add_own_habit)
    _colours()


def _add_own_habit():
    """Keep the habit typed in the box to add when Next is pressed (the Add button, and Next)."""
    name = (st.session_state.get("ob_own_name") or "").strip()
    if not name:
        return
    link = st.session_state.get("ob_own_link")
    _ob().setdefault("own", []).append((name, None if link in (None, "No goal") else link))
    st.session_state["ob_own_name"] = ""


def _save_track():
    ob = _ob()
    _add_own_habit()
    goals = _my_goals()
    for i, g in goals:
        for j, s in enumerate(suggest.for_goal(g["title"])):
            if st.session_state.get(f"ob_sg_{i}_{j}"):
                apply_suggestion(s, g["id"], ob.get("goal_nums", {}).get(i, False))
    for name, goal_title in ob.get("own", []):
        gid = next((g["id"] for _, g in goals if g["title"] == goal_title), None)
        apply_suggestion({"kind": "habit", "name": name}, gid)
    ob["own"] = []
    for cid, name, *_ in _colour_options():                    # setup only adds: a category left off is not removed
        if name in (st.session_state.get("ob_cats") or []):
            ensure_category(cid)
    _make_own_category()


def _text_on(colour):
    """Black or white text, whichever reads better on a #RRGGBB colour."""
    r, g, b = (int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5))
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
    lum = 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    return "#000000" if (lum + 0.05) / 0.05 >= 1.05 / (lum + 0.05) else "#FFFFFF"


def _chip(name, colour):
    colour = gr.safe_colour(colour, "#999999")
    return (f'<span style="display:inline-block;margin:.15rem .3rem .15rem 0;padding:.15rem .65rem;border-radius:1rem;'
            f'background:{colour};color:{_text_on(colour)};font-size:.9rem">{escape(name)}</span>')


def _colour_options():
    """[(id, name, colour)] for the colour chips: every example, then categories that aren't one of them."""
    cats = store.load_categories().to_dict("records")
    have = {c["id"]: c for c in cats}
    by_name = {c["name"].lower(): c for c in cats}
    out = []
    for cid, name, colour, *_ in store.EXAMPLE_CATEGORIES:
        mine = have.get(cid) or by_name.get(name.lower())
        out.append((cid, name, mine["colour"] if mine else colour))
    shown = {o[0] for o in out} | {n.lower() for _, n, _ in out}
    out += [(c["id"], c["name"], c["colour"]) for c in cats if c["id"] not in shown and c["name"].lower() not in shown]
    return out


def _colours():
    """Colour your timetable: a chip to switch on for each category, and a box to add your own."""
    options = _colour_options()
    names = [n for _, n, _ in options]
    existing = {n.lower() for n in store.load_categories()["name"]}
    if "ob_cats" not in st.session_state:                      # seeded here, so the pills take no default
        st.session_state["ob_cats"] = [n for n in names if n.lower() in existing]
    on = st.session_state["ob_cats"]
    kit.subhead("Colour your timetable")
    st.caption("Tap a category to switch it on. Your modules and anything you picked above are already there.")
    st.html("".join(_chip(n, c) for _, n, c in options if n in on) or "<i>None switched on yet.</i>")
    st.pills("Categories", names, selection_mode="multi", key="ob_cats",
             label_visibility="collapsed")
    a, b, c = st.columns([3, 1, 1], vertical_alignment="bottom")
    a.text_input("Add your own category", key="ob_cat_name", placeholder="e.g. Lab work")
    b.color_picker("Colour", "#4E79A7", key="ob_cat_colour")
    c.button("Add", key="ob_cat_add", icon=":material/add:", on_click=_add_own_category)


def _make_own_category(required=False):
    """Add the category typed in the box (nothing if the name is empty, unless `required`), in the smallest
    group. Raises ValueError if it can't be added."""
    if not required and not (st.session_state.get("ob_cat_name") or "").strip():
        return
    name = st.session_state.get("ob_cat_name")
    add_category(name, st.session_state.get("ob_cat_colour") or "#4E79A7", default_group())
    st.session_state["ob_cat_name"] = ""
    st.session_state["ob_cats"] = [*(st.session_state.get("ob_cats") or []), name.strip()]


def _add_own_category():
    try:
        _make_own_category(required=True)
    except ValueError as e:
        st.session_state["ob_error"] = str(e)


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
    _ob()["added"] = added


def _week():
    ob = _ob()
    st.header("Your first week", anchor=False)
    st.caption("Press **Edit Home** at the top of Home to change what it shows.")
    sittings = first_week()
    ob["sittings"] = sittings
    added = ob.get("added")
    if added is not None:
        st.success(f"Added {added} block{'s' if added != 1 else ''} to your Plan." if added else
                   "Nothing was added: that time is taken now.", icon=":material/check_circle:")
    if not sittings:
        if added is None:
            kit.empty("Nothing to suggest yet. Hours goals, like a module's study time, get sittings here, in your free time.",
                      ":material/info:")
        return
    hours = sum(store.slot_of(s["end"]) - store.slot_of(s["start"]) for s in sittings) / 2
    st.markdown(f"Here's how your goals could fit in the next 7 days: {pace.fmt(hours)} h in free time. "
                "Nothing already in your timetable moves.")
    _grid(sittings)
    st.button("Add to my Plan", key="ob_week_add", type="primary", icon=":material/playlist_add:", on_click=_add_week)


STEP_BODY = {"calendars": _calendars, "modules": _modules, "goals": _goals, "track": _track, "week": _week}
SAVE = {"calendars": _save_calendars, "modules": _save_modules, "goals": _save_goals, "track": _save_track}


def _typed(key):
    return bool((st.session_state.get(key) or "").strip())


def _filled(key):
    """Has this step got something in it this run: typed, ticked or connected? (Cheap checks, no writing.)
    The main button says Next if so, and Skip if not."""
    ss, ob = st.session_state, _ob()
    if key == "calendars":
        return any(_typed(f"ob_link_{k}") or bool(ob.get(f"found_{k}")) for k in ("uni", "canvas"))
    if key == "modules":
        return (_typed("ob_new_module") or any(ss.get(f"ob_keep_{_cand_key(c)}", True) for c in ob.get("cands", []))
                or bool(ob.get("new_modules"))
                or any(k in ss and float(ss[k]) != v for k, v in ob.get("hours_start", {}).items())
                or any(v not in (None, "Not linked") for k, v in ss.items() if k.startswith("ob_course_")))
    if key == "goals":
        return any(_typed(f"ob_goal_{i}") for i in range(len(GOAL_SLOTS)))
    if key == "track":
        return (_typed("ob_own_name") or _typed("ob_cat_name") or bool(ob.get("own"))
                or any(v for k, v in ss.items() if k.startswith("ob_sg_"))
                or bool(set(ss.get("ob_cats") or []) - set(store.load_categories()["name"])))
    return False


def _go(index, save=None):
    """Move to a step, first saving the one we're leaving (Next); an error stays on it."""
    if save:
        try:
            SAVE[save]()
        except ValueError as e:
            st.session_state["ob_error"] = str(e)
            return
    st.session_state["wizard_step"] = index


def wizard(finish, skip=None):
    """The full-screen setup: no sidebar. `finish` is called when it's done, `skip` (default: finish) when setup is skipped."""
    st.html("<style>[data-testid='stSidebar'], [data-testid='stSidebarCollapsedControl'] { display: none; }</style>")
    listed = steps()
    step = min(st.session_state.setdefault("wizard_step", 0), len(listed) - 1)
    key = listed[step][0]
    _, mid, _ = st.columns([1, 3, 1])
    with mid:
        st.caption(" · ".join(f"**{n}**" if i == step else n for i, (_, n, _) in enumerate(listed)))
        st.progress((step + 1) / len(listed))
        if error := st.session_state.pop("ob_error", None):
            st.error(error, icon=":material/error:")
        if key == "welcome":
            _welcome()
        else:
            STEP_BODY[key]()
        st.divider()
        last = step == len(listed) - 1
        if key == "welcome":
            st.button("Skip setup", key="wiz_skip_all", on_click=skip or finish)
            return
        back, main = st.columns([1, 1])
        back.button("Back", key="wiz_back", on_click=_go, args=(step - 1,), icon=":material/arrow_back:")
        if last:
            main.button("Start using Venato", key="wiz_finish", type="primary", on_click=finish, width="stretch")
        elif _filled(key):
            main.button("Next", key="wiz_next", type="primary", on_click=_go, args=(step + 1, key if key in SAVE else None),
                        width="stretch", icon=":material/arrow_forward:")
        else:
            # Same save as Next: a click can arrive from the previous run's button, drawn before the text was typed.
            main.button("Skip", key="wiz_skip", on_click=_go, args=(step + 1, key if key in SAVE else None),
                        width="stretch")
