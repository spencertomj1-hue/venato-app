"""
The weekly review on screen: a pop-up the first time Venato is opened after 7pm
on Sunday (maybe_show), and the history at the bottom of Stats (history).
The numbers come from venato/review.py.
"""

from datetime import timedelta

import altair as alt
import pandas as pd
import streamlit as st

from venato import blocks, regional
from venato import review
from venato import store
from venato.ui import kit


def _week_title(first):
    last = first + timedelta(days=6)
    return f"{regional.day_month(first, weekday=False)} – {regional.day_month(last, weekday=False, year=True)}"


def _delta(now, before, unit="", fmt="{:g}"):
    if now is None:
        return "–", None
    return fmt.format(now) + unit, (None if before is None else round(now - before, 1))


POPUP = "review_popup"
KEPT = {"yes": "Yes", "partly": "Partly", "no": "No"}


def _save_kept(first, key):
    pick = st.session_state.get(key)
    store.save_review(first, kept=next((k for k, v in KEPT.items() if v == pick), None))


def _whole_app(key):
    """After a callback that changes something outside the review (the chat, the timetable, the page):
    on Review the review is a fragment, so rerun the whole app (the pop-up's rerun already is)."""
    if key != POPUP:
        st.rerun(scope="app")


def _ask_claude(s, key):
    from venato.ui import chat
    chat.ask(f"Review my week of {_week_title(s['first'])} (weekly_review with date {s['first'].isoformat()}). "
             "Give me an honest verdict in a few lines: what went well, what slipped and why, "
             "and one concrete thing to change next week.")
    _whole_app(key)


def _confirm_days(days, key):
    for d in days:
        store.confirm_day(d)
    st.toast(f"Confirmed {len(days)} day{'s' if len(days) != 1 else ''}", icon=":material/task_alt:")
    _whole_app(key)


def _open_day(day, key):
    from venato.ui import timetable
    timetable._review(store._as_date(day))
    _whole_app(key)


def _promise(s, key):
    """Last week's "what will you do differently?", and did they."""
    with st.container(border=True):
        st.markdown(f":material/flag: **Last week you said:** {s['promise']}")
        kept = s["review"].get("kept")
        k = f"{key}_kept"
        st.segmented_control("Did you?", list(KEPT.values()), default=KEPT.get(kept), key=k,
                             on_change=_save_kept, args=(s["first"], k))


def _unconfirmed(s, key):
    days = s["unconfirmed"]
    n = len(days)
    with st.container(border=True):
        names = ", ".join(regional.day_month(store._as_date(d)) for d in days)
        st.markdown(f":orange[:material/warning:] **{n} day{'s' if n != 1 else ''} not confirmed** ({names}): "
                    "their time isn't counted above.")
        row = st.container(horizontal=True, gap="small")
        row.button("Confirm as is", key=f"{key}_confirm", type="primary", icon=":material/task_alt:",
                   on_click=_confirm_days, args=(days, key), help="Their Actual on the Timetable is what you did")
        row.button("Check on the Timetable", key=f"{key}_open", icon=":material/edit_calendar:",
                   on_click=_open_day, args=(days[0], key), help=f"Open {regional.day_month(store._as_date(days[0]))}")


def _trends(first, key):
    rows = review.trend(first)
    if sum(r["followed_pct"] is not None or r["actual_hours"] > 0 for r in rows) < 2:
        return                                    # nothing to draw a line through yet
    df = pd.DataFrame(rows)
    df["Week"] = df["week"].map(lambda w: regional.day_month(w, weekday=False))
    charts = [("Plan followed (%)", "followed_pct"), ("Hours logged", "actual_hours")]
    if blocks.is_on("log"):
        charts += [("Avg mood", "mood"), ("Avg sleep (h)", "sleep")]
    charts = [(t, c) for t, c in charts if df[c].notna().sum() >= 2]
    if not charts:
        return
    with st.expander(f"Last {len(rows)} weeks", icon=":material/show_chart:"):
        cols = st.columns(len(charts))
        for col, (title, c) in zip(cols, charts):
            with col:
                d = df[["Week", c]].dropna().rename(columns={c: title})
                kit.show(kit.line_chart(d, "Week", title, height=120, title=title,
                                        x_axis=alt.Axis(labels=False, title=None)), key=f"{key}_trend_{c}")


def render(first, key):
    """The review of the week starting `first`. `key` keeps widget keys apart (dialog vs Stats)."""
    s = review.summary(first)
    if not s["complete"]:
        st.caption("This week isn't over yet: these are the numbers so far.")

    # --- The verdict, and last week's promise ---
    head = st.container(horizontal=True, vertical_alignment="center", gap="small")
    head.markdown(f"**{s['headline']}**", width="stretch")
    if store.ai_enabled():
        head.button("Ask Claude", key=f"{key}_ask", icon=":material/auto_awesome:", on_click=_ask_claude, args=(s, key),
                    help="Claude reads this week's numbers and gives you its take in the chat")
    if s["unconfirmed"]:
        _unconfirmed(s, key)
    if s["promise"]:
        _promise(s, key)

    # --- The headline numbers, with the change from the week before ---
    log_on = blocks.is_on("log")                 # habits, mood and the journal are Daily Log's
    habits_hit = sum(h["hit"] for h in s["habits"])
    t, b4 = s["todos"], s["before"]
    a, b, *rest = st.columns(4 if log_on else 3)
    habits_col, todos_col = (rest[0], rest[1]) if log_on else (None, rest[0])
    pct = s["followed_pct"]
    a.metric("Plan followed", f"{pct}%" if pct is not None else "–",
             delta=None if pct is None or b4["followed_pct"] is None else f"{pct - b4['followed_pct']:+d} pts",
             help="The share of your planned time where you did what you planned (same category). "
                  "Change from the week before.")
    b.metric("Hours logged", f"{s['actual_hours']:g} h",
             delta=None if not b4["actual_hours"] or not s["complete"] else f"{s['actual_hours'] - b4['actual_hours']:+g} h",
             delta_color="off", help=f"{s['planned_hours']:g} h were planned. Change from the week before.")
    if log_on:
        habits_col.metric("Habits on target", f"{habits_hit}/{len(s['habits'])}" if s["habits"] else "–")
    done, total = t["weekly_done"] + t["daily_done"], t["weekly"] + t["daily"]
    todos_col.metric("To-dos done", f"{done}/{total}" if total else "–",
                     delta=None if not total or not b4["todos"] or not s["complete"] else f"{done - b4['todos_done']:+d}",
                     help="Change in to-dos done from the week before.")
    if log_on:
        log = s["log"]
        a, b, c, p, d = st.columns(5)
        for col, name, k, unit, fmt in ((a, "Mood", "mood", "/10", "{:g}"), (b, "Sleep", "sleep", " h", "{:g}"),
                                        (c, "Energy", "energy", "/10", "{:g}"), (p, "Productivity", "productivity", "/10", "{:g}"),
                                        (d, "Water", "water", "", "{}")):
            now, before = log[k]["now"], log[k]["before"]
            if k == "water":
                value = regional.water_text(now) if now is not None else "–"
                delta = None if now is None or before is None else \
                    round(regional.water_out(now) - regional.water_out(before), 1)
            else:
                value, delta = _delta(now, before, unit, fmt)
            col.metric(f"Avg {name.lower()}", value, delta=delta, help="Change from the week before.")
    st.caption((f"Daily log filled in on {s['days_logged']} of 7 days. " if log_on else "")
               + f"Time is counted from {s['days_confirmed']} of {s['days_so_far']} days confirmed on the timetable.")

    # --- Time: planned vs done per category ---
    if s["time"]:
        rows = [{"Category": x["category"], "Hours": x[track], "Track": label}
                for x in s["time"] for track, label in (("plan", "Planned"), ("actual", "Done"))]
        kit.show(kit.bar_chart(pd.DataFrame(rows), "Category", "Hours", color="Track", title="Time: planned vs done",
                               labels=".1f", palette={"Planned": kit.muted(), "Done": regional_accent()}),
                 key=f"{key}_time")
        short = review.gaps(s["time"])
        if short:
            st.caption("Biggest gaps: " + "; ".join(
                f"planned {g['plan']:g} h of {g['category']}, did {g['actual']:g} h" for g in short) + ".")
    _trends(s["first"], key)

    left, right = st.columns(2)
    with left:
        if s["habits"]:
            st.markdown("**Habits**")
            for h in s["habits"]:
                mark = ":material/check_circle:" if h["hit"] else ":material/radio_button_unchecked:"
                st.markdown(f"{mark} {h['name']} · {h['ticks']}/{h['target']}")
        dl = s["deadlines"]
        if dl["met"] or dl["missed"] or dl["upcoming"]:
            st.markdown("**Deadlines**")
            for x in dl["met"]:
                st.markdown(f":material/check_circle: {x['title']} (done)")
            for x in dl["missed"]:
                st.markdown(f":red[:material/cancel: {x['title']} (not ticked off)]")
            for x in dl["upcoming"]:
                st.markdown(f":material/schedule: Next week: {x['title']}, {regional.day_month(x['due'])}")
    with right:
        if s.get("goals"):
            from venato.ui import goal_time
            st.markdown("**Goal pace**")
            for x in s["goals"]:
                st.markdown(f"{goal_time.badge(x['state'])} {goal_time.md(x['goal']['title'])}  \n"
                            f":gray[{goal_time.md(x['text'].split(': ', 1)[1].rsplit(' · ', 1)[0])}]")
        if s["journal"]:
            st.markdown(f"**Journal** ({len(s['journal'])} entr{'y' if len(s['journal']) == 1 else 'ies'})")
            for e in reversed(s["journal"]):
                line = e["text"].strip().splitlines()[0]
                st.markdown(f"{regional.day_month(e['date'])} · {line[:90]}{'…' if len(line) > 90 else ''}")

    for sec in s.get("sections", []):
        st.markdown(f"**{sec['title']}**")
        for line in sec["lines"]:
            st.markdown(line)

    # --- Reflections ---
    st.markdown("**Looking back**")
    saved = s["review"]
    with st.form(f"{key}_reflect", border=False):
        went = st.text_area("What went well?", saved.get("went_well") or "", height=90)
        change = st.text_area("What will you do differently next week?", saved.get("to_change") or "", height=90)
        if st.form_submit_button("Save", type="primary", icon=":material/save:"):
            store.save_review(first, went_well=went, to_change=change, seen=True)
            st.toast("Saved", icon=":material/check_circle:")


def regional_accent():
    from venato.ui import appearance
    return appearance.accent()


@st.dialog("Your week", width="large")
def _dialog(first):
    st.subheader(_week_title(first), anchor=False)
    render(first, key=POPUP)
    if st.button("Done", key="review_popup_done", type="primary", icon=":material/check:",
                 help="Close the review; it won't pop up again (it's on the Review page any time)"):
        store.save_review(first, seen=True)
        st.rerun()


def maybe_show():
    """Once per session: the week's review, if it's due (after 7pm Sunday) and not finished with yet.
    It only counts as seen once it's saved or Done is pressed: closed by accident, it comes back next time."""
    if st.session_state.get("review_checked"):
        return
    st.session_state["review_checked"] = True
    week = review.should_show()
    if week:
        _dialog(week)


@st.fragment
def history():
    """Stats page: pick a week to look at its review again (or this week so far). A fragment: picking a week
    or saving a reflection redraws just this."""
    st.subheader("Weekly reviews", anchor=False)
    this_week = store.week_start_of(store.local_today())
    weeks = [store._as_date(r["week_start"]) for r in store.reviews()]
    options = [this_week] + [w for w in weeks if w != this_week]
    if len(options) == 1:
        st.caption("Your first review appears on Sunday evening. Meanwhile, here's this week so far.")
    pick = st.selectbox("Week", options, key="review_week",
                        format_func=lambda w: ("This week so far: " if w == this_week else "") + _week_title(w))
    with st.container(border=True):
        render(pick, key=f"review_{pick.isoformat()}")
