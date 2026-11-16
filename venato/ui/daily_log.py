"""
Daily Log page: everything happens in the journal, a book with one page per day.
The left page has the day's mood, energy and sleep, its training session(s) and its
habits to tick; the right page is the journal itself. Under the book: "Jump to a day"
(the month calendar) and "Manage habits". Home's habits are here too.

Journal: journal_component.js/.css draws the book; journal.py saves pages and turns
"quoted" text into that day's to-dos and ^marked^ text into that week's.
The month calendar (calendar_component.*) is folded away under "Jump to a day".
"""

import hashlib
from datetime import date, timedelta
from pathlib import Path

import streamlit as st

from venato import journal
from venato import regional
from venato import store
from venato import undo

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
    "What drained your energy today? What gave you energy?",
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


def _short(d):
    return f"{d:%a} {d.day} {d:%b}"


# ---------------------------------------------------------------------------
# Calendar and journal callbacks
# ---------------------------------------------------------------------------

def _go_to(day):
    st.session_state["log_day"] = day
    st.session_state["log_month"] = day.replace(day=1)


def _on_select():
    picked = (st.session_state["log_calendar"]["select"] or {}).get("date")
    if picked:
        st.session_state["log_day"] = date.fromisoformat(picked)
        st.session_state["journal_open"] = True


def _on_month():
    nav = st.session_state["log_calendar"]["nav"] or {}
    if nav.get("dir") == 0:
        _go_to(store.local_today())
        return
    month = st.session_state["log_month"]
    # First day of the previous / next month.
    shifted = (month - timedelta(days=1)) if nav.get("dir", 0) < 0 else (month + timedelta(days=32))
    st.session_state["log_month"] = shifted.replace(day=1)


def _on_journal_open():
    st.session_state["journal_open"] = bool((st.session_state["journal"]["open"] or {}).get("open"))
    st.session_state.pop("journal_notice", None)


def _on_journal_save():
    value = st.session_state["journal"]["save"] or {}
    day = value.get("date")
    if not day or day > store.local_today().isoformat():
        return
    added = journal.save(day, value.get("text", ""), make_todos=bool(value.get("final")))
    if added:
        names = {"daily": "that day's", "weekly": "that week's"}
        st.session_state["journal_notice"] = "Added to to-dos: " + "; ".join(
            f"{title} ({names[period]})" for period, title in added)


def _on_journal_log():
    value = st.session_state["journal"]["log"] or {}
    if value.get("field") in store.ENTRY_FIELDS and value.get("date", "9") <= store.local_today().isoformat():
        store.set_entry_field(value["date"], value["field"], value.get("value"))


def _on_journal_track():
    value = st.session_state["journal"]["track"] or {}
    if store.find_day_tracker(value.get("id")) and value.get("date", "9") <= store.local_today().isoformat():
        store.set_day_value(value["date"], value["id"], value.get("value"))


def _on_journal_habit():
    value = st.session_state["journal"]["habit"] or {}
    if value.get("id") is not None and value.get("date", "9") <= store.local_today().isoformat():
        with store.db() as conn:
            store.set_habit_done(conn, int(value["id"]), value["date"], bool(value.get("done")))


def _on_journal_session():
    value = st.session_state["journal"]["session"] or {}
    if value.get("id"):
        store.update_session(value["id"], done=bool(value.get("done")))


def _on_journal_nav():
    day = (st.session_state["journal"]["nav"] or {}).get("date")
    if day:
        _go_to(min(date.fromisoformat(day), store.local_today()))
        st.session_state.pop("journal_notice", None)


PAGE = "Daily Log"      # sidebar label (also what Home's habits "Manage" switches to)


def _journal(selected, today):
    d = selected.isoformat()
    entry = store.get_entry(d)
    logged = store.day_values(d)
    habits = [{"id": hid, "name": name, "done": d in store.get_habit_dates(hid)} for hid, name in store.get_habits()]
    plan = store.active_plan()
    sessions = [{"id": s["id"], "title": s["title"], "km": f"{s['distance_km']:g}" if s["distance_km"] else None,
                 "done": s["done"]} for s in (store.plan_sessions(plan["id"]) if plan else []) if s["date"] == d]
    _journal_component(
        data={
            "open": st.session_state.get("journal_open", False),
            "date": selected.isoformat(), "today": today.isoformat(),
            "title": f"{selected:%A} {selected.day} {selected:%B %Y}",
            "prevTitle": _short(selected - timedelta(days=1)),
            "text": entry.get("notes") or "", "notice": st.session_state.get("journal_notice"),
            "mood": entry.get("mood"), "energy": entry.get("energy"), "sleep": entry.get("sleep"),
            "trackers": [{**t, "value": logged.get(t["id"])} for t in store.day_trackers()],
            "habits": habits, "sessions": sessions,
        },
        key="journal", on_open_change=_on_journal_open, on_save_change=_on_journal_save,
        on_nav_change=_on_journal_nav, on_log_change=_on_journal_log, on_habit_change=_on_journal_habit,
        on_session_change=_on_journal_session, on_track_change=_on_journal_track,
    )


def page_daily_log():
    st.header("Daily Log", anchor=False)
    today = store.local_today()
    selected = min(st.session_state.setdefault("log_day", today), today)
    month = st.session_state.setdefault("log_month", today.replace(day=1))

    _journal(selected, today)

    # --- Month calendar (6 weeks from the week's first day on/before the 1st), to jump to a day ---
    with st.expander("Jump to a day", icon=":material/calendar_month:"):
        first = store.week_start_of(month)
        entries = store.entries_between(first.isoformat(), (first + timedelta(days=41)).isoformat())
        _calendar_component(
            data={
                "month": f"{month:%Y-%m}",
                "today": today.isoformat(),
                "selected": selected.isoformat(),
                "weekStart": regional.week_start(), "weekdays": regional.weekday_names(),
                "waterUnit": regional.water_short(),
                "days": {e["date"]: {k: e.get(k) for k in ("mood", "sleep", "energy", "productivity", "notes")}
                         | {"water": regional.water_out(e.get("water"))}
                         for e in entries.to_dict("records")},
            },
            key="log_calendar", on_select_change=_on_select, on_nav_change=_on_month,
        )

    _manage_habits()
    _manage_trackers()

    _past_entries()


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

def _toggle_habit(habit_id, day, key):
    """Checkbox callback: save the new tick state straight away."""
    with store.db() as conn:
        store.set_habit_done(conn, habit_id, day, st.session_state[key])


def _open_habits():
    st.session_state["page"] = PAGE         # the sidebar radio's key; button callbacks run before it's drawn


def render_home_habits():
    """Home: today's habits to tick, each with the last 7 days and its current streak."""
    today = store.local_today()
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]
    accent = st.get_option("theme.primaryColor") or "#ff4b4b"
    head, link = st.columns([4, 1], vertical_alignment="center")
    head.markdown("**Habits**")
    link.button("Manage", key="home_habits_manage", type="tertiary", on_click=_open_habits)

    habits = store.get_habits()
    if not habits:
        st.caption("No habits yet. Add some on the Daily Log page.")
        return
    st.html(f"""<style>
      .hb-week {{ display: flex; gap: 4px; justify-content: flex-end; }}
      .hb-week i {{ width: 11px; height: 11px; border-radius: 3px; background: rgba(128, 128, 128, 0.18); }}
      .hb-week i.on {{ background: {accent}; }}
      .hb-week i.today {{ outline: 1.5px solid rgba(128, 128, 128, 0.6); outline-offset: 1px; }}
    </style>""")
    d = today.isoformat()
    for habit_id, name in habits:
        done = store.get_habit_dates(habit_id)
        _, current, per_week = store.habit_progress(habit_id, done, today)
        key = f"home_habit_{habit_id}_{d}"
        tick, week, streak = st.columns([5, 3, 2], vertical_alignment="center")
        st.session_state[key] = d in done          # always what's saved (it may have been ticked in the journal)
        tick.checkbox(name, key=key, on_change=_toggle_habit, args=(habit_id, d, key))
        cells = "".join(
            f'<i class="{"on" if x.isoformat() in done else ""}{" today" if x == today else ""}" '
            f'title="{x:%a} {x.day} {x:%b}"></i>' for x in days)
        week.html(f'<div class="hb-week" title="Last 7 days">{cells}</div>')
        if per_week:      # a weekly target: this week's count, and the streak in weeks
            streak.caption(f"{store.week_ticks(done, today)}/{per_week} this wk"
                           + (f" · :material/local_fire_department: {current}w" if current else ""))
        else:
            streak.caption(f":material/local_fire_department: {current}" if current else "–")   # current streak


# "How often" choices: index 0 is every day, index n is n times a week.
OFTEN = ["Every day"] + [f"{n} time{'s' * (n > 1)} a week" for n in range(1, 8)]


def _manage_trackers():
    """The user's own day trackers: numbers to log each day on the journal's left page."""
    trackers = store.day_trackers()
    with st.expander("Manage trackers"):
        st.caption("Numbers you want to log each day, e.g. *Reading · hours · 0.5* or *Coffee · cups · 1*. "
                   "They appear on the journal's left page and in Stats.")
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


def _manage_habits():
    """Add, rename and remove habits (ticking them is on the journal's left page and on Home)."""
    habits = store.get_habits()
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
            with st.form("rename_habit", clear_on_submit=True):
                a, b = st.columns(2)
                old = a.selectbox("Rename a habit", list(names))
                new = b.text_input("New name")
                if st.form_submit_button("Rename") and new.strip():
                    try:
                        store.rename_habit(names[old], new)
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))
            st.caption("Renaming keeps its history and streaks.")

            to_remove = st.selectbox("Remove a habit", list(names))
            st.caption("Removing a habit also deletes its history (you can undo it straight after).")
            if st.button("Remove habit"):
                undo.checkpoint(f"Removed the habit '{to_remove}' and its history")
                store.delete_habit(names[to_remove])
                st.rerun()
