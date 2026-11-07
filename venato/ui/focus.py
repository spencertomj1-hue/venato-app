"""
The Focus page and its Home widget: start a Pomodoro or a stopwatch, the live timer, today's
sessions, and time by day and by activity. The logic is in venato/blocks/focus.py.
"""

import time
from datetime import timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from venato import store
from venato.blocks import focus

HERE = Path(__file__).parent

_timer = st.components.v2.component(
    "venato_focus",
    html='<div class="fc-root"></div>',
    css=(HERE / "components" / "focus_component.css").read_text(encoding="utf-8"),
    js=(HERE / "components" / "focus_component.js").read_text(encoding="utf-8"),
)


def _on_action(key):
    act = (st.session_state.get(key) or {}).get("action") or {}
    name = act.get("name")
    if name == "pause":
        focus.pause()
    elif name == "resume":
        focus.resume()
    elif name == "cancel":
        focus.cancel()
        st.session_state["focus_msg"] = "Cancelled: nothing logged."
    elif name in ("stop", "skip"):
        session, note = focus.stop()
        if session and session["kind"] != "break":
            st.session_state["focus_msg"] = f"Logged {session['label']}: {session['minutes']:.0f} min. {note}".strip()
    elif name == "done":
        st.session_state["focus_msg"] = focus.finish_if_due()


def _draw_timer(key, compact=False):
    r = focus.running()
    data = {"state": "idle", "compact": compact}
    if r:
        data.update(state="paused" if r["paused_at"] else "running", kind=r["kind"], label=r["label"],
                    planned=None if r["planned"] is None else r["planned"] * 60,
                    elapsed=focus.elapsed(r), drawnAt=time.time() * 1000)
    _timer(data=data, key=key, on_action_change=lambda: _on_action(key))
    return r


def duration(minutes):
    """'25 min' under an hour, else '1.5 h'."""
    return f"{minutes:.0f} min" if minutes < 60 else f"{minutes / 60:.1f} h"


def _message():
    msg = st.session_state.pop("focus_msg", "")
    if msg:
        st.toast(msg, icon=":material/timer:")


def _category_options():
    cats = store.load_categories()
    return ["(from the activity)"] + list(cats["name"])


def _start_form(prefix, compact=False):
    s = focus.settings()
    last = st.session_state.get("focus_last_label", "")
    if compact:
        a, b = st.columns([3, 2], vertical_alignment="bottom")
        label = a.text_input("What are you focusing on?", value=last, key=f"{prefix}_label",
                             placeholder="e.g. Essay")
        if b.button(f"Focus {s['focus_minutes']} min", key=f"{prefix}_go", type="primary", width="stretch",
                    icon=":material/play_arrow:"):
            _start(label, s["focus_minutes"], "focus", None)
        return
    label = st.text_input("What are you working on?", value=last, key=f"{prefix}_label", placeholder="e.g. Essay")
    a, b, c = st.columns([2, 2, 2], vertical_alignment="bottom")
    mode = a.segmented_control("Mode", ["Pomodoro", "Stopwatch"], default="Pomodoro", key=f"{prefix}_mode")
    minutes = b.number_input("Minutes", 1, 240, int(s["focus_minutes"]), key=f"{prefix}_minutes",
                             disabled=mode == "Stopwatch")
    category = c.selectbox("Timetable category", _category_options(), key=f"{prefix}_cat",
                           help="Which category its block in the Actual column gets")
    if st.button("Start", key=f"{prefix}_go", type="primary", icon=":material/play_arrow:"):
        cid = None if category == "(from the activity)" else store.resolve_category(category=category)
        if mode == "Stopwatch":
            _start(label, None, "track", cid)
        else:
            _start(label, minutes, "focus", cid)


def _start(label, minutes, kind, cid):
    label = (label or "").strip() or "Focus"
    st.session_state["focus_last_label"] = label
    cid = cid or store.resolve_category(label=label)
    try:
        focus.start(label, minutes, kind, cid)
    except focus.FocusError as e:
        st.error(str(e))
        return
    st.rerun()


def _summary():
    today = store.local_today()
    week0 = store.week_start_of(today)
    by_label_today, by_day = focus.totals(today, today)
    by_label_week, _ = focus.totals(week0, today)
    a, b, c = st.columns(3)
    a.metric("Today", duration(by_day.get(today.isoformat(), 0)))
    b.metric("This week", duration(sum(by_label_week.values())))
    n = focus.streak(today)
    c.metric("Streak", f"{n} day{'s' * (n != 1)}")
    return today


def render_page():
    st.title("Focus")
    _message()
    focus.finish_if_due()                         # a timer that ran out while away
    r = _draw_timer("focus_timer")
    if not r:
        _start_form("focus")
    st.divider()
    today = _summary()

    tab_today, tab_week, tab_settings = st.tabs(["Today", "Last 4 weeks", "Settings"])
    with tab_today:
        rows = focus.sessions(today, today, kinds=("focus", "track", "break"))
        if not rows:
            st.caption("Nothing yet today.")
        for s in reversed(rows):
            a, b = st.columns([6, 1], vertical_alignment="center")
            icon = {"focus": ":material/timer:", "track": ":material/schedule:", "break": ":material/coffee:"}[s["kind"]]
            extra = "" if s["completed"] else " · stopped early"
            tt = " · in timetable" if s["in_timetable"] else ""
            a.markdown(f"{icon} **{s['label']}** · {s['started'][11:16]}–{s['ended'][11:16]} · "
                       f"{s['minutes']:.0f} min{extra}{tt}")
            if b.button("", icon=":material/delete:", key=f"focus_del_{s['id']}", help="Delete this session"):
                from venato import undo
                undo.checkpoint(f"Deleted the {s['label']} session")
                focus.delete(s["id"])
                st.rerun()
        with st.expander("Log time you've already spent", icon=":material/add:"):
            with st.form("focus_manual", clear_on_submit=True, border=False):
                a, b, c, d = st.columns([3, 1, 2, 2])
                label = a.text_input("Activity")
                minutes = b.number_input("Minutes", 1, 24 * 60, 30)
                day = c.date_input("Day", today)
                start_t = d.time_input("Started at", None, step=300)
                if st.form_submit_button("Log it"):
                    try:
                        session, note = focus.log_manual(label or "Focus", minutes, day,
                                                         start_t.strftime("%H:%M") if start_t else None,
                                                         store.resolve_category(label=label))
                        st.success(f"Logged {session['minutes']:.0f} min of {session['label']}. {note}".strip())
                    except focus.FocusError as e:
                        st.error(str(e))
    with tab_week:
        first = today - timedelta(days=27)
        rows = focus.sessions(first, today)
        if not rows:
            st.caption("No focus or tracked time in the last 4 weeks.")
        else:
            df = pd.DataFrame(rows)
            df["day"] = pd.to_datetime(df["started"].str[:10])
            df["hours"] = df["minutes"] / 60
            daily = df.groupby(["day", "label"], as_index=False)["hours"].sum()
            fig = px.bar(daily, x="day", y="hours", color="label", title="Hours per day",
                         labels={"day": "", "hours": "Hours", "label": ""})
            fig.update_xaxes(tickformat="%-d %b")
            st.plotly_chart(fig, width="stretch")
            by_label = df.groupby("label", as_index=False)["hours"].sum().sort_values("hours", ascending=False)
            st.dataframe(by_label.rename(columns={"label": "Activity", "hours": "Hours"}).round(1),
                         hide_index=True, width="stretch")
    with tab_settings:
        s = focus.settings()
        a, b, c, d = st.columns(4)
        new = {
            "focus_minutes": a.number_input("Focus (min)", 1, 240, int(s["focus_minutes"]), key="focus_set_f"),
            "short_break": b.number_input("Short break (min)", 1, 60, int(s["short_break"]), key="focus_set_s"),
            "long_break": c.number_input("Long break (min)", 1, 120, int(s["long_break"]), key="focus_set_l"),
            "long_every": d.number_input("Long break every", 1, 12, int(s["long_every"]), key="focus_set_n",
                                         help="focus sessions"),
            "auto_breaks": st.toggle("Start breaks automatically", s["auto_breaks"], key="focus_set_auto"),
            "to_timetable": st.toggle(f"Add sessions of {focus.MIN_FOR_TIMETABLE}+ minutes to the Actual timetable",
                                      s["to_timetable"], key="focus_set_tt"),
        }
        if new != s:
            focus.save_settings(**new)


def render_home():
    st.markdown("**Focus**")
    _message()
    focus.finish_if_due()
    r = _draw_timer("home_focus_timer", compact=True)
    if not r:
        _start_form("home_focus", compact=True)
    today = store.local_today()
    _, by_day = focus.totals(today, today)
    mins = by_day.get(today.isoformat(), 0)
    if mins:
        st.caption(f"{duration(mins)} focused today")
