"""
Habits page and Home's Habits tile (the `habits` block: its own block since #20, no longer part of the Daily Log).

Page: this week as a grid (a row per habit, a tick per day up to today, its progress on the right), then
adding, changing and removing habits. Home: today's ticks with each habit's current streak.
"""

from datetime import timedelta

import streamlit as st

from venato import store
from venato import undo
from venato.ui import kit

PAGE = "Habits"

# "How often" choices: index 0 is every day, index n is n times a week.
OFTEN = ["Every day"] + [f"{n} time{'s' * (n > 1)} a week" for n in range(1, 8)]


def _toggle(habit_id, day, key, home=False):
    """Checkbox callback: save the tick straight away. The ticks are a fragment, so only they rerun; on Home the
    whole app reruns when a goal counts this habit (its bar is outside the fragment)."""
    with store.db() as conn:
        store.set_habit_done(conn, habit_id, day, st.session_state[key])
    if home:
        kit.rerun_app_if({f"habit:{habit_id}"})


def _open_page():
    st.session_state["page"] = PAGE         # the router (nav.py); set in a callback, before the page is drawn


# ---------------------------------------------------------------------------
# Home
# ---------------------------------------------------------------------------

def render_home():
    """Home's Habits widget: today's habits to tick, each with its current streak."""
    head = st.container(horizontal=True, vertical_alignment="center")
    kit.subhead("Habits", head, width="stretch")
    head.button("Manage", key="home_habits_manage", type="tertiary", on_click=_open_page)
    if not store.get_habits():
        st.caption("No habits yet. Add them on the Habits page.")
        return
    _home_rows()


@st.fragment
def _home_rows():
    """Home's habit ticks, side by side (a fragment: ticking one reruns just these), each with its current streak
    after its name ("Exercise · 5": in days, or weeks for a habit with a weekly target)."""
    today = store.local_today()
    d = today.isoformat()
    box = st.container(key="home_habits", horizontal=True, gap="small")
    for habit_id, name in store.get_habits():
        done = store.get_habit_dates(habit_id)
        streak = store.habit_progress(habit_id, done, today)[1]
        key = f"home_habit_{habit_id}_{d}"
        box.checkbox(f"{name} · {streak}" if streak else name, value=d in done, key=key, on_change=_toggle,
                     args=(habit_id, d, key, True), width="content")


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

def render_page():
    st.title("Habits", anchor=False)
    if not store.get_habits():
        kit.empty("No habits yet. Add one below: something to tick off every day, or so many times a week.")
    else:
        _week_grid()
    _manage()


@st.fragment
def _week_grid():
    """This week: a row per habit with a tick for each day (none after today) and its progress line."""
    today = store.local_today()
    first = store.week_start_of(today)
    days = [first + timedelta(days=i) for i in range(7)]
    widths = [3] + [1] * 7 + [4]
    head = st.columns(widths, vertical_alignment="bottom")
    for col, day in zip(head[1:8], days):
        col.caption(f"**{day:%a}**" if day == today else f"{day:%a}")
    for habit_id, name in store.get_habits():
        done = store.get_habit_dates(habit_id)
        row = st.columns(widths, vertical_alignment="center")
        row[0].markdown(name)
        for col, day in zip(row[1:8], days):
            d = day.isoformat()
            key = f"habit_{habit_id}_{d}"
            col.checkbox(f"{name} on {day:%A}", value=d in done, key=key, disabled=day > today,
                         label_visibility="collapsed", on_change=_toggle, args=(habit_id, d, key))
        row[8].caption(store.habit_progress(habit_id, done, today)[0])


def _manage():
    habits = store.get_habits()
    st.subheader("Add a habit", anchor=False)
    with st.form("add_habit", clear_on_submit=True):
        a, b, c = st.columns([3, 2, 1], vertical_alignment="bottom")
        new_name = a.text_input("New habit", placeholder="e.g. Stretch")
        how = b.selectbox("How often", OFTEN, key="habit_new_often")
        if c.form_submit_button("Add habit") and new_name.strip():
            store.add_habit(new_name.strip(), OFTEN.index(how) or None)
            st.rerun()
    if not habits:
        return

    with st.expander("Change or remove a habit"):
        targets = store.habit_targets()
        names = {name: habit_id for habit_id, name in habits}
        a, b, c = st.columns([3, 2, 1], vertical_alignment="bottom")
        which = a.selectbox("Change how often", list(names), key="habit_often_which")
        how = b.selectbox("How often", OFTEN, index=targets.get(names[which], 0), key=f"habit_often_{names[which]}")
        if c.button("Save", key="habit_often_save"):
            store.set_habit_target(names[which], OFTEN.index(how) or None)
            st.rerun()

        to_remove = st.selectbox("Remove a habit", list(names))
        st.caption("Removing a habit also deletes its history (you can undo it straight after).")
        if st.button("Remove habit"):
            undo.checkpoint(f"Removed the habit '{to_remove}' and its history")
            store.delete_habit(names[to_remove])
            st.rerun()
