"""
Daily Log page (the day's log and habits) and Home's habits.

Daily log: a journal. The page leads with the selected day's journal box (today's prompt), with sleep
and water beside it when switched on (Settings -> Daily Log). A month calendar (calendar_component.js/.css)
marks the days that have an entry; clicking a day opens it. Habits follow.
Habits: tick habits for a day, see streaks, add/remove habits.
"""

import hashlib
from datetime import date, timedelta
from pathlib import Path

import streamlit as st

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


PAGE = "Daily Log"      # sidebar label (also what Home's habits "Manage" switches to)


def page_daily_log():
    st.header("Daily Log", anchor=False)
    _day_card()
    _past_entries()


@st.fragment
def _day_card():
    """The selected day's journal box (with sleep and water beside it when on), the month calendar and the
    day's habits: a fragment, so picking a day or a month redraws just this. Saving reruns the app (Past
    entries below shows the journal)."""
    today = store.local_today()
    selected = st.session_state.setdefault("log_day", today)
    month = st.session_state.setdefault("log_month", today.replace(day=1))
    sleep_on, water_on = store.tracks_sleep(), store.tracks_water()
    d = selected.isoformat()
    entry = store.get_entry(d)

    # --- The journal box, for the selected day ---
    st.subheader(nice_date(selected), anchor=False)
    if selected > today:
        st.info("You can't log a day that hasn't happened yet. Pick today or an earlier day.")
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
    st.session_state["page"] = PAGE         # the sidebar radio's key; button callbacks run before it's drawn


def render_home_habits():
    """Home's Habits widget: today's habits to tick, each with the last 7 days and its current streak."""
    accent = st.get_option("theme.primaryColor") or "#ff4b4b"
    head = st.container(horizontal=True, vertical_alignment="center")
    head.markdown("**Habits**", width="stretch")
    head.button("Manage", key="home_habits_manage", type="tertiary", on_click=_open_habits)
    if not store.get_habits():
        st.caption("No habits yet. Add them on the Daily Log.")
        return
    _home_habit_rows(accent)


def _write_today():
    st.session_state["log_day"] = store.local_today()
    st.session_state["log_month"] = store.local_today().replace(day=1)
    st.session_state["page"] = PAGE


def render_home_journal():
    """Home's Journal widget: today's entry so far (or today's prompt), and Write to open it on the Daily Log."""
    today = store.local_today()
    head = st.container(horizontal=True, vertical_alignment="center")
    head.markdown("**Journal**", width="stretch")
    head.button("Write", key="home_journal_write", type="tertiary", icon=":material/edit:", on_click=_write_today)
    text = (store.get_journal(today.isoformat()) or "").strip()
    if text:
        st.caption(text if len(text) <= 280 else text[:280].rsplit(" ", 1)[0] + "…")
    else:
        st.caption(f"Nothing yet today. {prompt_for(today)}")


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
