"""
Daily Log page (the journal, the day's log and habits) and Home's habits.

Journal: a book at the top (journal_component.js/.css), one page per day. The right page is
the day's writing (entries.notes, saved as you type); the left page logs mood, energy,
productivity, sleep, water, the user's own day trackers and the day's habits. "Quoted"
text becomes a to-do for that day and ^marked^ text one for that week (journal.py).

Daily log: a month calendar (calendar_component.js/.css) showing each day's
mood, sleep, energy, productivity and water; clicking a day shows its notes, and the form below
saves the entry for the selected day.
Habits: tick habits for a day, see streaks, add/remove habits.
"""

import hashlib
from datetime import date, timedelta
from pathlib import Path

import streamlit as st

from venato import journal
from venato import regional
from venato import store
from venato import undo
from venato.ui import kit

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


PAGE = "Daily Log"      # sidebar label (also what Home's habits "Manage" switches to)


# ---------------------------------------------------------------------------
# The journal (a book at the top of the page)
# ---------------------------------------------------------------------------

def _short(d):
    return regional.day_month(d)


def _go_to(day):
    st.session_state["log_day"] = day
    st.session_state["log_month"] = day.replace(day=1)


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
    field = value.get("field")
    if field in store.ENTRY_FIELDS and value.get("date", "9") <= store.local_today().isoformat():
        amount = value.get("value")
        if field == "water" and amount is not None:
            amount = regional.water_in(amount)            # the user's unit -> litres
        store.set_entry_field(value["date"], field, amount)


def _on_journal_track():
    value = st.session_state["journal"]["track"] or {}
    if store.find_day_tracker(value.get("id")) and value.get("date", "9") <= store.local_today().isoformat():
        store.set_day_value(value["date"], value["id"], value.get("value"))


def _on_journal_habit():
    value = st.session_state["journal"]["habit"] or {}
    if value.get("id") is not None and value.get("date", "9") <= store.local_today().isoformat():
        with store.db() as conn:
            store.set_habit_done(conn, int(value["id"]), value["date"], bool(value.get("done")))


def _on_journal_nav():
    day = (st.session_state["journal"]["nav"] or {}).get("date")
    if day:
        _go_to(min(date.fromisoformat(day), store.local_today()))
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
            "prevTitle": _short(selected - timedelta(days=1)),
            "text": entry.get("notes") or "", "notice": st.session_state.get("journal_notice"),
            "mood": entry.get("mood"), "energy": entry.get("energy"), "productivity": entry.get("productivity"),
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
    """The user's own day trackers: numbers to log each day on the journal's left page."""
    trackers = store.day_trackers()
    with st.expander("Manage trackers"):
        st.caption("Numbers you want to log each day, e.g. *Reading · hours · 0.5* or *Coffee · cups · 1*. "
                   "They appear on the journal's left page.")
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


def page_daily_log():
    st.header("Daily Log", anchor=False)
    _journal(store.local_today())
    _day_card()
    _manage_trackers()
    _past_entries()


@st.fragment
def _day_card():
    """The month calendar, the selected day's card, its habits and the form to save it: a fragment, so picking
    a day or a month redraws just this. Saving reruns the app (Past entries below shows the journal)."""
    today = store.local_today()
    selected = st.session_state.setdefault("log_day", today)
    month = st.session_state.setdefault("log_month", today.replace(day=1))
    if st.session_state.get("journal_drawn") not in (None, min(selected, today)):
        st.rerun()                                # the journal above shows another day: turn it too

    # --- Month calendar (6 weeks from the Monday on/before the 1st) ---
    first = store.week_start_of(month)
    entries = store.entries_between(first.isoformat(), (first + timedelta(days=41)).isoformat())
    _calendar_component(
        data={
            "month": f"{month:%Y-%m}",
            "today": today.isoformat(),
            "selected": selected.isoformat(),
            "weekStart": regional.week_start(), "weekdays": regional.weekday_names(), "waterUnit": regional.water_short(),
            "days": {e["date"]: {k: e.get(k) for k in ("mood", "sleep", "energy", "productivity", "notes")}
                     | {"water": regional.water_out(e["water"])}
                     for e in entries.to_dict("records")},
        },
        key="log_calendar", on_select_change=_on_select, on_nav_change=_on_month,
    )

    # --- The selected day ---
    d = selected.isoformat()
    entry = store.get_entry(d)
    with st.container(border=True):
        st.subheader(nice_date(selected), anchor=False)
        if entry:
            a, b, c, p, w = st.columns(5)
            a.metric("Mood", f"{entry['mood']}/10" if entry.get("mood") else "–")
            b.metric("Sleep", f"{entry['sleep']:g} h" if entry.get("sleep") is not None else "–")
            c.metric("Energy", f"{entry['energy']}/10" if entry.get("energy") else "–")
            p.metric("Productivity", f"{entry['productivity']}/10" if entry.get("productivity") else "–")
            w.metric("Water", regional.water_text(entry.get("water")))
            st.markdown(entry["notes"].replace("\n", "  \n") if entry.get("notes") else "*No journal entry.*")
        else:
            st.caption("Nothing logged for this day yet.")

    _habits_for(selected, today)

    # --- Save an entry for the selected day ---
    if selected > today:
        st.info("You can't log a day that hasn't happened yet. Pick today or an earlier day.")
        return
    st.subheader("Save entry", anchor=False)
    # Widget keys include the date, so the form reloads when you pick another day, and a hash of the
    # saved entry, so it shows what Claude just wrote instead of a stale draft.
    v = f"{d}_{hashlib.sha1(repr(sorted(entry.items())).encode('utf-8')).hexdigest()[:8]}"
    with st.form(f"entry_form_{v}"):
        mood = st.slider("Mood", 1, 10, int(entry.get("mood") or 5), key=f"mood_{v}")
        sleep = st.number_input(
            "Sleep (hours)", 0.0, 24.0, float(entry.get("sleep") or 7.0), step=0.5, key=f"sleep_{v}"
        )
        energy = st.slider("Energy", 1, 10, int(entry.get("energy") or 5), key=f"energy_{v}")
        productivity = st.slider("Productivity", 1, 10, int(entry.get("productivity") or 5), key=f"prod_{v}",
                                 help="How productive did the day feel?")
        litres = regional.water_unit() == "litres"
        water = st.number_input(f"Water ({regional.water_unit()})", 0.0, 15.0 if litres else 500.0,
                                regional.water_out(entry.get("water")),
                                step=0.25 if litres else 4.0, format="%.2f" if litres else "%.0f",
                                placeholder="e.g. 2", key=f"water_{v}_{regional.water_unit()}", help="Leave empty if you didn't track it.")
        notes = st.text_area("Journal", entry.get("notes") or "", height=260, key=f"notes_{v}",
                             placeholder=prompt_for(selected), help="The day's notes: write as much as you like.")
        if st.form_submit_button(f"Save {nice_date(selected)}", type="primary"):
            with store.db() as conn:
                if entry:
                    undo.checkpoint(f"Updated the log for {nice_date(selected)}")
                store.save_entry(conn, d, mood, sleep, energy, notes.strip() or None, regional.water_in(water), productivity)
            st.toast(f"Saved {nice_date(selected)}.")
            st.rerun()   # refresh the calendar
    if entry:
        st.caption("An entry already exists for this day — saving will update it.")


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
    st.session_state["page"] = PAGE         # the sidebar radio's key; button callbacks run before it's drawn


def render_home_habits():
    """Home: today's habits to tick, each with the last 7 days and its current streak."""
    accent = st.get_option("theme.primaryColor") or "#ff4b4b"
    head = st.container(horizontal=True, vertical_alignment="center")
    head.markdown("**Habits**", width="stretch")
    head.button("Manage", key="home_habits_manage", type="tertiary", on_click=_open_habits)

    habits = store.get_habits()
    if not habits:
        st.caption("No habits yet. Add some on the Daily Log page.")
        return
    _home_habit_rows(accent)


@st.fragment
def _home_habit_rows(accent):
    """Home's habit ticks (a fragment: ticking one reruns just these rows)."""
    today = store.local_today()
    days = [today - timedelta(days=i) for i in range(6, -1, -1)]
    habits = store.get_habits()
    st.html(f"""<style>
      .hb-week {{ display: flex; gap: 4px; justify-content: flex-end; }}
      .hb-week i {{ width: 11px; height: 11px; border-radius: 3px; background: rgba(128, 128, 128, 0.18); }}
      .hb-week i.on {{ background: {accent}; }}
      .hb-week i.today {{ outline: 1.5px solid rgba(128, 128, 128, 0.6); outline-offset: 1px; }}
      .st-key-home_habits {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); column-gap: 28px; }}
    </style>""")
    d = today.isoformat()
    box = st.container(key="home_habits")     # two habits a row when wide, to keep Home short
    for habit_id, name in habits:
        done = store.get_habit_dates(habit_id)
        _, current, per_week = store.habit_progress(habit_id, done, today)
        key = f"home_habit_{habit_id}_{d}"
        tick, week, streak = box.columns([5, 3, 2], vertical_alignment="center")
        tick.checkbox(name, value=d in done, key=key, on_change=_toggle_habit, args=(habit_id, d, key, True))
        cells = "".join(
            f'<i class="{"on" if x.isoformat() in done else ""}{" today" if x == today else ""}" '
            f'title="{x:%a} {x.day} {x:%b}"></i>' for x in days)
        week.html(f'<div class="hb-week" title="Last 7 days">{cells}</div>')
        if per_week:      # a weekly target: this week's count, and the streak in weeks
            streak.caption(f"{store.week_ticks(done, today)}/{per_week} this wk"
                           + (f" · :material/local_fire_department: {current}w" if current else ""))
        else:
            streak.caption(f":material/local_fire_department: {current}" if current else "–")   # current streak


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
