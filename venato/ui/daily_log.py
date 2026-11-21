"""
Daily Log page (the day's log and habits) and Home's habits.

Daily log: a journal. The page leads with the selected day's journal box (today's prompt), with sleep
and water beside it when switched on (Settings -> Daily Log). A month calendar (calendar_component.js/.css)
marks the days that have an entry; clicking a day opens it. Habits follow.
Habits: tick habits for a day, see streaks, add/remove habits.

The journal book (journal_component.js/.css) sits above it all, closed until opened. Open, it is the
writing page for the selected day (entries.notes, saved as you type) and the journal box steps aside;
its left page has sleep and water (when switched on), the user's own day trackers and the day's habits.
"Quoted" text becomes a to-do for that day and ^marked^ text one for that week (venato/journal.py).
"""

import hashlib
from datetime import date, timedelta
from pathlib import Path

import streamlit as st

from venato import journal
from venato import regional
from venato import store
from venato import undo
from venato.ui import glance, kit

HERE = Path(__file__).parent

_calendar_component = st.components.v2.component(
    "log_calendar",
    html='<div class="cal-root"></div>',
    css=(HERE / "components" / "calendar_component.css").read_text(encoding="utf-8"),
    js=(HERE / "components" / "calendar_component.js").read_text(encoding="utf-8"),
)


_journal_component = st.components.v2.component(
    "journal",
    html='<div class="jn-root"></div>',
    css=(HERE / "components" / "journal_component.css").read_text(encoding="utf-8"),
    js=(HERE / "components" / "journal_component.js").read_text(encoding="utf-8"),
)


def nice_date(d):
    return regional.long_date(d)


# The journal box's placeholder: the same prompt all day, a different one each day.
PROMPTS = [
    "What went well today, and why?",
    "What's on your mind right now?",
    "What did you learn today?",
    "What are you grateful for?",
    "What drained you today? What gave you a lift?",
    "What would make tomorrow a good day?",
    "Who did you enjoy spending time with?",
    "What's something you're putting off, and what's the first small step?",
    "What surprised you today?",
    "How did you look after yourself today?",
    "What's worrying you, and how much of it is in your control?",
    "What are you looking forward to?",
]


def prompt_for(day):
    return PROMPTS[day.toordinal() % len(PROMPTS)]


# ---------------------------------------------------------------------------
# Daily log
# ---------------------------------------------------------------------------

def _on_select():
    picked = (st.session_state["log_calendar"]["select"] or {}).get("date")
    if picked:
        st.session_state["log_day"] = date.fromisoformat(picked)


def _on_month():
    nav = st.session_state["log_calendar"]["nav"] or {}
    if nav.get("dir") == 0:
        st.session_state["log_day"] = store.local_today()
        st.session_state["log_month"] = store.local_today().replace(day=1)
        return
    month = st.session_state["log_month"]
    # First day of the previous / next month.
    shifted = (month - timedelta(days=1)) if nav.get("dir", 0) < 0 else (month + timedelta(days=32))
    st.session_state["log_month"] = shifted.replace(day=1)


PAGE = "Daily Log"      # page name (also what Home's habits "Manage" switches to)


def page_daily_log():
    st.header("Daily Log", anchor=False)
    _journal(store.local_today())
    _day_card()
    _manage_trackers()
    _past_entries()


# ---------------------------------------------------------------------------
# The journal book
# ---------------------------------------------------------------------------

def _not_future(day):
    return bool(day) and day <= store.local_today().isoformat()


def _on_journal_open():
    st.session_state["journal_open"] = bool((st.session_state["journal"]["open"] or {}).get("open"))
    st.session_state.pop("journal_notice", None)


def _on_journal_save():
    value = st.session_state["journal"]["save"] or {}
    if not _not_future(value.get("date")):
        return
    added = journal.save(value["date"], value.get("text", ""), make_todos=bool(value.get("final")))
    if added:
        names = {"daily": "that day's", "weekly": "that week's"}
        st.session_state["journal_notice"] = "Added to to-dos: " + "; ".join(
            f"{title} ({names[period]})" for period, title in added)


def _on_journal_log():
    value = st.session_state["journal"]["log"] or {}
    field = value.get("field")
    if field in store.ENTRY_FIELDS and _not_future(value.get("date")):
        amount = value.get("value")
        if field == "water" and amount is not None:
            amount = regional.water_in(amount)            # the user's unit -> litres
        store.set_entry_field(value["date"], field, amount)


def _on_journal_track():
    value = st.session_state["journal"]["track"] or {}
    if store.find_day_tracker(value.get("id")) and _not_future(value.get("date")):
        store.set_day_value(value["date"], value["id"], value.get("value"))


def _on_journal_habit():
    value = st.session_state["journal"]["habit"] or {}
    if value.get("id") is not None and _not_future(value.get("date")):
        with store.db() as conn:
            store.set_habit_done(conn, int(value["id"]), value["date"], bool(value.get("done")))


def _on_journal_nav():
    day = (st.session_state["journal"]["nav"] or {}).get("date")
    if day:
        _open_day(min(date.fromisoformat(day), store.local_today()))
        st.session_state.pop("journal_notice", None)


def _journal(today):
    """The book, open on the selected day (never a future one)."""
    selected = min(st.session_state.setdefault("log_day", today), today)
    st.session_state["journal_drawn"] = selected
    d = selected.isoformat()
    entry = store.get_entry(d)
    logged = store.day_values(d)
    litres = regional.water_unit() == "litres"
    habits = [{"id": hid, "name": name, "done": d in store.get_habit_dates(hid)} for hid, name in store.get_habits()]
    _journal_component(
        data={
            "open": st.session_state.get("journal_open", False),
            "date": d, "today": today.isoformat(),
            "title": f"{selected:%A} {selected.day} {selected:%B %Y}",
            "prevTitle": regional.day_month(selected - timedelta(days=1)),
            "text": entry.get("notes") or "", "prompt": prompt_for(selected),
            "notice": st.session_state.get("journal_notice"),
            "showSleep": store.tracks_sleep(), "showWater": store.tracks_water(),
            "sleep": entry.get("sleep"), "water": regional.water_out(entry.get("water")),
            "waterUnit": regional.water_short(), "waterStep": 0.25 if litres else 4, "waterMax": 15 if litres else 500,
            "trackers": [{**t, "value": logged.get(t["id"])} for t in store.day_trackers()],
            "habits": habits, "sessions": [],
        },
        key="journal", on_open_change=_on_journal_open, on_save_change=_on_journal_save,
        on_nav_change=_on_journal_nav, on_log_change=_on_journal_log, on_habit_change=_on_journal_habit,
        on_track_change=_on_journal_track,
    )


def _manage_trackers():
    """The user's own day trackers: numbers to log each day on the journal book's left page."""
    trackers = store.day_trackers()
    with st.expander("Manage trackers"):
        st.caption("Numbers you want to log each day, e.g. *Reading · hours · 0.5* or *Coffee · cups · 1*. "
                   "They appear on the journal book's left page.")
        with st.form("add_tracker", clear_on_submit=True):
            a, b, c, go = st.columns([3, 2, 1, 1], vertical_alignment="bottom")
            name = a.text_input("New tracker")
            unit = b.text_input("Unit", placeholder="e.g. hours, times")
            step = c.number_input("Step", 0.25, 100.0, 1.0, 0.25, help="How much + and − change it by")
            if go.form_submit_button("Add") and name.strip():
                try:
                    store.add_day_tracker(name, unit, step)
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
        for t in trackers:
            a, b, c, x = st.columns([3, 2, 1, 1], vertical_alignment="bottom")
            name = a.text_input("Name", t["name"], key=f"trk_name_{t['id']}")
            unit = b.text_input("Unit", t["unit"], key=f"trk_unit_{t['id']}")
            step = c.number_input("Step", 0.25, 100.0, float(t["step"]), 0.25, key=f"trk_step_{t['id']}")
            if (name, unit, step) != (t["name"], t["unit"], float(t["step"])):
                try:
                    store.update_day_tracker(t["id"], name=name, unit=unit, step=step)
                except ValueError as e:
                    st.error(str(e))
            if x.button("Remove", key=f"trk_del_{t['id']}", help="Also deletes what's been logged for it"):
                undo.checkpoint(f"Removed the tracker '{t['name']}' and its history")
                store.delete_day_tracker(t["id"])
                st.rerun()


@st.fragment
def _day_card():
    """The selected day's journal box (with sleep and water beside it when on), the month calendar and the
    day's habits: a fragment, so picking a day or a month redraws just this. Saving reruns the app (Past
    entries below shows the journal)."""
    today = store.local_today()
    selected = st.session_state.setdefault("log_day", today)
    month = st.session_state.setdefault("log_month", today.replace(day=1))
    if st.session_state.get("journal_drawn") not in (None, min(selected, today)):
        st.rerun(scope="app")                     # the journal book above shows another day: turn it too
    sleep_on, water_on = store.tracks_sleep(), store.tracks_water()
    d = selected.isoformat()
    entry = store.get_entry(d)

    # --- The journal box, for the selected day ---
    st.subheader(nice_date(selected), anchor=False)
    if selected > today:
        st.info("You can't log a day that hasn't happened yet. Pick today or an earlier day.")
    elif st.session_state.get("journal_open"):
        st.caption("You're writing this day in the journal book above.")
    else:
        _entry_form(selected, d, entry, sleep_on, water_on)

    # --- Month calendar (6 weeks from the Monday on/before the 1st), marking days with an entry ---
    first = store.week_start_of(month)
    entries = store.entries_between(first.isoformat(), (first + timedelta(days=41)).isoformat())
    days = calendar_days(entries.to_dict("records"), sleep_on, water_on)
    _calendar_component(
        data={
            "month": f"{month:%Y-%m}",
            "today": today.isoformat(),
            "selected": selected.isoformat(),
            "weekStart": regional.week_start(), "weekdays": regional.weekday_names(), "waterUnit": regional.water_short(),
            "showSleep": sleep_on, "showWater": water_on,
            "days": days,
        },
        key="log_calendar", on_select_change=_on_select, on_nav_change=_on_month,
    )

    _habits_for(selected, today)


def calendar_days(entries, sleep_on, water_on):
    """What the calendar draws for each day: whether it has a journal entry, and sleep / water when switched on."""
    days = {}
    for e in entries:
        day = {"notes": bool((e.get("notes") or "").strip())}
        if sleep_on:
            day["sleep"] = e.get("sleep")
        if water_on:
            day["water"] = regional.water_out(e.get("water"))
        days[e["date"]] = day
    return days


def _entry_form(selected, d, entry, sleep_on, water_on):
    # Widget keys include the date, so the form reloads when you pick another day, and a hash of the
    # saved entry, so it shows what Claude just wrote instead of a stale draft.
    v = f"{d}_{hashlib.sha1(repr(sorted(entry.items())).encode('utf-8')).hexdigest()[:8]}"
    with st.form(f"entry_form_{v}", border=False):
        extras = sleep_on or water_on
        journal, side = st.columns([3, 1], gap="medium") if extras else (st.container(), None)
        notes = journal.text_area("Journal", entry.get("notes") or "", height=260, key=f"notes_{v}",
                                  placeholder=prompt_for(selected), help="The day's notes: write as much as you like.")
        sleep = water = None
        if side is not None:
            with side:
                if sleep_on:
                    sleep = st.number_input("Sleep (hours)", 0.0, 24.0, entry.get("sleep"), step=0.5,
                                            placeholder="e.g. 7.5", key=f"sleep_{v}", help="Leave empty if you didn't track it.")
                if water_on:
                    litres = regional.water_unit() == "litres"
                    water = st.number_input(f"Water ({regional.water_unit()})", 0.0, 15.0 if litres else 500.0,
                                            regional.water_out(entry.get("water")),
                                            step=0.25 if litres else 4.0, format="%.2f" if litres else "%.0f",
                                            placeholder="e.g. 2", key=f"water_{v}_{regional.water_unit()}",
                                            help="Leave empty if you didn't track it.")
        if st.form_submit_button(f"Save {nice_date(selected)}", type="primary"):
            text = notes.strip() or None
            fields = {"notes": text}
            if sleep_on:
                fields["sleep"] = sleep
            if water_on:
                fields["water"] = regional.water_in(water)
            if not entry and not any(x is not None for x in fields.values()):
                st.toast("Nothing to save yet.")
            else:
                with store.db() as conn:
                    if entry:
                        undo.checkpoint(f"Updated the log for {nice_date(selected)}")
                    store.save_entry(conn, d, **fields)
                st.toast(f"Saved {nice_date(selected)}.")
                st.rerun()   # refresh the calendar
    if entry and (entry.get("notes") or entry.get("sleep") is not None or entry.get("water") is not None):
        st.caption("An entry already exists for this day: saving will update it.")


def _open_day(day):
    st.session_state["log_day"] = day
    st.session_state["log_month"] = day.replace(day=1)


def _past_entries():
    """Earlier journal entries (the days' notes), newest first, with a search box."""
    st.subheader("Past entries", anchor=False)
    query = st.text_input("Search", placeholder="Search your journal", label_visibility="collapsed",
                          key="journal_search")
    entries = store.journal_entries(query or None, limit=None if query else 30)
    if not entries:
        st.caption("No matches." if query else "Nothing written yet.")
    for e in entries:
        d = store._as_date(e["date"])
        first_line = e["text"].strip().splitlines()[0]
        preview = first_line[:70] + ("…" if len(first_line) > 70 else "")
        with st.expander(f"**{regional.day_month(d, year=True)}** · {preview}", expanded=bool(query) and len(entries) <= 3):
            st.markdown(e["text"].replace("\n", "  \n"))
            st.button("Open this day", key=f"journal_open_{e['date']}", on_click=_open_day, args=(d,),
                      icon=":material/edit:")


# ---------------------------------------------------------------------------
# Habits
# ---------------------------------------------------------------------------

def _toggle_habit(habit_id, day, key, home=False):
    """Checkbox callback: save the new tick state straight away. The ticks are a fragment, so only they
    rerun; on Home the whole app reruns when a goal counts this habit (its bar is outside the fragment)."""
    with store.db() as conn:
        store.set_habit_done(conn, habit_id, day, st.session_state[key])
    if home:
        kit.rerun_app_if({f"habit:{habit_id}"})


def _open_habits():
    st.session_state["page"] = PAGE         # the router (nav.py); set in a callback, before the page is drawn


def render_home_habits():
    """Home's Habits widget: today's habits to tick, each with the last 7 days and its current streak."""
    head = st.container(horizontal=True, vertical_alignment="center")
    kit.subhead("Habits", head, width="stretch")
    head.button("Manage", key="home_habits_manage", type="tertiary", on_click=_open_habits)
    if not store.get_habits():
        st.caption("No habits yet. Add them on the Daily Log.")
        return
    _home_habit_rows()


def _write_today():
    st.session_state["log_day"] = store.local_today()
    st.session_state["log_month"] = store.local_today().replace(day=1)
    st.session_state["page"] = PAGE


def render_home_journal():
    """Home's Journal widget: the week's days written (dots, the first day of the week first) and the streak from
    2 days, then today's entry so far (or today's prompt); Write opens it on the Daily Log."""
    today = store.local_today()
    head = st.container(horizontal=True, vertical_alignment="center")
    kit.subhead("Journal", head, width="stretch")
    head.button("Write", key="home_journal_write", type="tertiary", icon=":material/edit:", on_click=_write_today)
    from venato import tile_status
    w = tile_status.journal_week(today)
    flags = [written for _, written in w["days"]]
    n = w["streak"]
    a, b = st.columns([3, 2], vertical_alignment="center", gap="small")
    with a:
        st.html(glance.dots(flags, f"Written {sum(flags)} of 7 days this week",
                            [store._as_date(d).strftime("%a")[0] for d, _ in w["days"]]))
    if n >= 2:
        b.caption(f"{n}-day streak")
    text = (store.get_journal(today.isoformat()) or "").strip()
    if text:
        st.caption(text if len(text) <= 280 else text[:280].rsplit(" ", 1)[0] + "…")
    else:
        st.caption(f"Nothing yet today. {prompt_for(today)}")


@st.fragment
def _home_habit_rows():
    """Home's habit ticks, side by side (a fragment: ticking one reruns just these), each with its current streak
    after its name ("Exercise · 5"; the Daily Log's own rule, in days or weeks). The rest is on the Daily Log."""
    today = store.local_today()
    d = today.isoformat()
    box = st.container(key="home_habits", horizontal=True, gap="small")
    for habit_id, name in store.get_habits():
        done = store.get_habit_dates(habit_id)
        streak = store.habit_progress(habit_id, done, today)[1]
        key = f"home_habit_{habit_id}_{d}"
        box.checkbox(f"{name} · {streak}" if streak else name, value=d in done, key=key, on_change=_toggle_habit,
                     args=(habit_id, d, key, True), width="content")


@st.fragment
def _habit_ticks(day, today):
    """The selected day's habit ticks with their progress (a fragment: ticking one reruns just these; nothing
    else on the Daily Log shows habits)."""
    d = day.isoformat()
    for habit_id, name in store.get_habits():
        done_dates = store.get_habit_dates(habit_id)
        progress, _, _ = store.habit_progress(habit_id, done_dates, min(day, today))
        key = f"habit_{habit_id}_{d}"
        left, right = st.columns([3, 2])
        left.checkbox(name, value=d in done_dates, key=key, disabled=day > today,
                      on_change=_toggle_habit, args=(habit_id, d, key))
        right.caption(progress)


# "How often" choices: index 0 is every day, index n is n times a week.
OFTEN = ["Every day"] + [f"{n} time{'s' * (n > 1)} a week" for n in range(1, 8)]


def _habits_for(day, today):
    """The selected day's habits to tick (not for future days), with streaks, and adding/removing habits."""
    st.subheader("Habits", anchor=False)
    habits = store.get_habits()
    if not habits:
        st.caption("No habits yet. Add one below.")
    else:
        _habit_ticks(day, today)

    with st.expander("Manage habits"):
        with st.form("add_habit", clear_on_submit=True):
            a, b, c = st.columns([3, 2, 1], vertical_alignment="bottom")
            new_name = a.text_input("New habit")
            how = b.selectbox("How often", OFTEN, key="habit_new_often")
            if c.form_submit_button("Add habit") and new_name.strip():
                store.add_habit(new_name.strip(), OFTEN.index(how) or None)
                st.rerun()

        if habits:
            targets = store.habit_targets()
            names = {name: habit_id for habit_id, name in habits}
            a, b, c = st.columns([3, 2, 1], vertical_alignment="bottom")
            which = a.selectbox("Change how often", list(names), key="habit_often_which")
            how = b.selectbox("How often", OFTEN, index=targets.get(names[which], 0), key=f"habit_often_{names[which]}")
            if c.button("Save", key="habit_often_save"):
                store.set_habit_target(names[which], OFTEN.index(how) or None)
                st.rerun()

        if habits:
            names = {name: habit_id for habit_id, name in habits}
            to_remove = st.selectbox("Remove a habit", list(names))
            st.caption("Removing a habit also deletes its history (you can undo it straight after).")
            if st.button("Remove habit"):
                undo.checkpoint(f"Removed the habit '{to_remove}' and its history")
                store.delete_habit(names[to_remove])
                st.rerun()
