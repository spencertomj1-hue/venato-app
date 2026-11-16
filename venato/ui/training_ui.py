"""
Training page: the 8-week half-marathon plan (training.py builds it, store.py
keeps it). Each week is a section with its sessions to tick off; the current
week is open. Each session's ⋯ changes it, logs the distance really run and
notes, or moves it to another day; "Edit the plan" changes every session in one
table. Home shows today's session.
"""

from datetime import date, time, timedelta
from html import escape

import streamlit as st

from venato import store
from venato import tools
from venato import training

PAGE = "Training"

# A colour per kind of session (a small dot, so the list reads at a glance).
KIND_COLOURS = {
    "easy": "#30A46C", "long": "#3E8EF7", "tempo": "#F5A524", "intervals": "#E5484D",
    "race_pace": "#8E4EC6", "strength": "#8B8D98", "shakeout": "#30A46C", "race": "#E5484D",
}


def _day(iso):
    d = date.fromisoformat(iso)
    return f"{d:%a} {d.day} {d:%b}"


def _km(x):
    return f"{x:g} km" if x is not None else ""


def _times():
    return {**training.DEFAULT_TIMES, **store.load_settings().get("training_times", {})}


def _time_input(label, value, key):
    """A quarter-hour time picker within the timetable's hours. Returns 'HH:mm'."""
    options = [store.slot_time(i) for i in range(store.SLOTS)]
    return st.selectbox(label, options, index=options.index(value) if value in options else 22, key=key)


def _toggle(session_id, key):
    store.update_session(session_id, done=st.session_state[key])


def _bar(fraction):
    colour = st.get_option("theme.primaryColor") or "#ff4b4b"
    return (f'<div style="height:8px;border-radius:4px;background:rgba(128,128,128,.18);overflow:hidden">'
            f'<div style="width:{round(100 * min(fraction, 1))}%;height:100%;background:{colour};border-radius:4px"></div></div>')


# ---------------------------------------------------------------------------
# One session row
# ---------------------------------------------------------------------------

def _session_row(s, today, statuses):
    key = f"tr_done_{s['id']}"
    block = store.session_block(s)
    tick, more = st.columns([12, 1], vertical_alignment="center")
    dot = KIND_COLOURS.get(s["kind"], "#999")
    when = "Today" if s["date"] == today else _day(s["date"])
    km = f" · {_km(s['distance_km'])}" if s["distance_km"] else ""
    ran = f" · ran {_km(s['actual_km'])}" if s["actual_km"] is not None else ""
    ran += " · missed" if statuses.get(s["block_id"]) is False else ""
    at = f" · {block['start']}" if block else ""
    st.session_state[key] = s["done"]          # always what's saved (it may have been ticked on Home)
    tick.checkbox(f"**{when}{at}** · {s['title']}{km}{ran}", key=key, on_change=_toggle, args=(s["id"], key))
    tick.html(f'<div style="margin:-10px 0 6px 28px;font-size:.82rem;opacity:.7;display:flex;gap:7px;align-items:baseline">'
              f'<span style="width:8px;height:8px;border-radius:2px;background:{dot};flex:none;align-self:center"></span>'
              f'<span>{escape(training.kind_name(s["kind"]))}: {escape(s["details"] or "")}'
              f'{"<br><i>" + escape(s["notes"]) + "</i>" if s["notes"] else ""}</span></div>')
    with more.popover("", icon=":material/more_horiz:", help="Change it, log the distance, or move it"):
        # The key includes what's saved, so the boxes always start from it.
        k = f"tr_{s['id']}_{s['title']}_{s['date']}_{s['distance_km']}_{s['actual_km']}_{block['start'] if block else ''}"
        title = st.text_input("Session", value=s["title"], key=f"{k}_title")
        plan_col, ran_col = st.columns(2)
        planned = plan_col.number_input("Planned (km)", min_value=0.0, step=0.5, format="%g", key=f"{k}_plan",
                                        value=float(s["distance_km"] or 0))
        logged = float(s["actual_km"] if s["actual_km"] is not None else s["distance_km"] or 0)
        actual = ran_col.number_input("Distance run (km)", min_value=0.0, step=0.5, format="%g", key=f"{k}_km",
                                      value=logged)
        notes = st.text_area("Notes", value=s["notes"] or "", key=f"{k}_notes", placeholder="How did it feel?")
        day_col, time_col = st.columns(2)
        new_day = day_col.date_input("Day", value=date.fromisoformat(s["date"]), key=f"{k}_date", format="DD/MM/YYYY")
        with time_col:
            new_time = _time_input("Time", block["start"] if block else training.start_time(s, _times()), f"{k}_time")
        on_tt = st.checkbox("On my timetable", value=bool(block), key=f"{k}_tt")
        if st.button("Save", key=f"{k}_save", type="primary", width="stretch"):
            title = title.strip() or s["title"]
            changes = {"title": title, "distance_km": planned or None, "notes": notes.strip() or None,
                       "date": new_day.isoformat()}
            if actual != logged or s["actual_km"] is not None:
                changes["actual_km"] = actual
            if actual != logged and actual and not s["done"]:
                changes["done"] = True            # a distance run means it's done, so it counts on Stats
            store.update_session(s["id"], **changes)
            moved = (block and new_time != block["start"]) or new_day.isoformat() != s["date"] \
                or title != s["title"] or (planned or None) != s["distance_km"]
            if on_tt and (not block or moved):
                tools.place_session(store.get_session(s["id"]), at=new_time)
            elif not on_tt and s["block_id"]:
                store.unplace_session(s["id"])
            st.rerun()
        if st.button("Delete session", key=f"{k}_delete", icon=":material/delete:", width="stretch"):
            store.delete_session(s["id"])
            st.rerun()


# ---------------------------------------------------------------------------
# Edit the plan: every session in one table
# ---------------------------------------------------------------------------

PLAN_ORDER = ["date", "title", "kind", "distance_km", "details"]
KIND_NAMES = {key: name for key, (name, _) in training.KINDS.items()}
KIND_IDS = {name: key for key, name in KIND_NAMES.items()}
PLAN_COLUMNS = {
    "date": st.column_config.DateColumn("Day", required=True, format="ddd D MMM YYYY"),
    "title": st.column_config.TextColumn("Session", required=True),
    "kind": st.column_config.SelectboxColumn("Type", options=list(KIND_IDS), required=True),
    "distance_km": st.column_config.NumberColumn("Planned (km)", min_value=0.0, step=0.5, format="%g"),
    "details": st.column_config.TextColumn("Details", width="large"),
}


def save_plan_edits(plan, sessions, rows):
    """Save the table: changed rows update their session, new rows add one, missing rows delete theirs. Returns how many changed."""
    import pandas as pd
    by_id = {s["id"]: s for s in sessions}
    on_timetable = any(s["block_id"] for s in sessions)
    clean = []
    for row in rows:
        if pd.isna(row.get("date")) or not str(row.get("title") or "").strip():
            raise ValueError("Every session needs a day and a name.")
        km = row.get("distance_km")
        details = row.get("details")
        clean.append({"id": row.get("id"), "date": pd.Timestamp(row["date"]).date().isoformat(),
                      "title": str(row["title"]).strip(), "kind": KIND_IDS.get(row.get("kind"), "easy"),
                      "distance_km": float(km) if pd.notna(km) and km else None,
                      "details": str(details).strip() or None if pd.notna(details) else None})
    changed = 0
    kept = set()
    for row in clean:
        old = by_id.get(row["id"])
        fields = {k: row[k] for k in PLAN_ORDER}
        if old is None:
            new_id = store.add_session(plan["id"], **{"day" if k == "date" else k: v for k, v in fields.items()})
            if on_timetable:
                tools.place_session(store.get_session(new_id), _times())
            changed += 1
            continue
        kept.add(old["id"])
        changes = {k: v for k, v in fields.items() if v != old[k]}
        if changes:
            block = store.session_block(old)
            store.update_session(old["id"], **changes)
            if block:                               # same start time, on its new day and at its new length
                tools.place_session(store.get_session(old["id"]), at=block["start"])
            changed += 1
    for session_id in set(by_id) - kept:
        store.delete_session(session_id)
        changed += 1
    return changed


def _edit_plan(plan, sessions):
    import pandas as pd
    # Behind a switch, so the table is only built when wanted.
    if not st.toggle("Edit the plan", key="tr_plan_edit"):
        return
    st.caption("Change any day, session or distance, then press Save. Add a session in the empty row at the "
               "bottom; to remove one, tick the box at the left of its row and press the bin above the table.")
    version = st.session_state.setdefault("tr_plan_version", 0)
    rows = [{**{k: s[k] for k in PLAN_ORDER}, "date": date.fromisoformat(s["date"]),
             "kind": KIND_NAMES.get(s["kind"], "Easy run"), "id": s["id"]} for s in sessions]
    table = st.data_editor(pd.DataFrame(rows, columns=[*PLAN_ORDER, "id"]), num_rows="dynamic", hide_index=True,
                           column_config=PLAN_COLUMNS, column_order=PLAN_ORDER, width="stretch",
                           key=f"tr_plan_table_{version}")
    if st.button("Save plan changes", type="primary", icon=":material/save:"):
        try:
            changed = save_plan_edits(plan, sessions, table.to_dict("records"))
        except ValueError as e:
            st.error(str(e))
        else:
            st.session_state["tr_plan_version"] = version + 1
            st.toast(f"Saved {changed} change{'s' * (changed != 1)}.", icon=":material/check_circle:")
            st.rerun()


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

def _no_plan():
    st.markdown(
        f"An **{training.WEEKS}-week half-marathon plan**, built on the usual coaching rules:\n\n"
        "- **3 sessions a week, rising to 5**, with distance growing about 10–20% a week\n"
        "- **An easier cutback week** in week 4, so your body absorbs the training\n"
        "- **Intensity building** from easy runs to tempo runs, intervals and race-pace work, "
        "with most running kept easy\n"
        "- **Strength sessions** from week 3, and a **taper** in the last two weeks so you race fresh\n\n"
        "It suits someone who can run 5–8 km comfortably now. Long runs go 8 → 15 km, then race day."
    )
    start = st.date_input("Start on", value=store.local_today() + timedelta(days=1), format="DD/MM/YYYY")
    first, race_day, sessions = training.generate(start)
    st.caption(f"Week 1 starts {_day(first.isoformat())}; race day is **{_day(race_day.isoformat())}** "
               f"({len(sessions)} sessions).")
    st.caption("The sessions go straight onto your timetable at these times (or the nearest free time that day). "
               "Move, change or delete them there like any other block.")
    times = _times()
    a, b = st.columns(2)
    with a:
        times["weekday"] = _time_input("Weekday sessions at", times["weekday"], "tr_new_weekday")
    with b:
        times["weekend"] = _time_input("Long runs and weekends at", times["weekend"], "tr_new_weekend")
    if st.button("Create my plan", type="primary", icon=":material/directions_run:"):
        store.create_plan(training.PLAN_NAME, first.isoformat(), race_day.isoformat(), sessions)
        tools.put_plan_on_timetable(times)
        st.rerun()


def render_page():
    st.header("Training")
    plan = store.active_plan()
    if not plan:
        _no_plan()
        st.divider()
        _gym_log()
        return

    sessions = store.plan_sessions(plan["id"])
    today = store.local_today().isoformat()
    days_to_go = (date.fromisoformat(plan["race_date"]) - date.fromisoformat(today)).days
    done = [s for s in sessions if s["done"]]
    run_km = sum((s["actual_km"] if s["actual_km"] is not None else s["distance_km"] or 0) for s in done)
    planned_km = sum(s["distance_km"] or 0 for s in sessions)
    upcoming = next((s for s in sessions if not s["done"] and s["date"] >= today), None)
    current = next((s["week"] for s in reversed(sessions) if s["date"] <= today), 1)

    when = (f"{days_to_go} days to go" if days_to_go > 1 else "tomorrow!" if days_to_go == 1
            else "today!" if days_to_go == 0 else "done")
    st.markdown(f"**{escape(plan['name'])}** · {_day(plan['start_date'])} → race day "
                f"**{_day(plan['race_date'])}** · {when}")

    a, b, c = st.columns(3)
    a.metric("Sessions done", f"{len(done)} / {len(sessions)}")
    b.metric("Distance run", f"{run_km:g} km", help=f"{planned_km:g} km in the whole plan, race included")
    c.metric("Next session", ("Today" if upcoming["date"] == today else _day(upcoming["date"])) if upcoming else "–")
    if upcoming:
        c.caption(f"{upcoming['title']}" + (f", {_km(upcoming['distance_km'])}" if upcoming["distance_km"] else ""))
    st.html(_bar(len(done) / len(sessions) if sessions else 0))

    statuses = store.event_statuses()
    for w in sorted({s["week"] for s in sessions}):
        ws = [s for s in sessions if s["week"] == w]
        km = sum(s["distance_km"] or 0 for s in ws)
        n_done = sum(1 for s in ws if s["done"])
        label = (f"Week {w} · {training.phase(w)} · {km:g} km · {len(ws)} sessions"
                 + (f" · {n_done}/{len(ws)} done" if n_done else "")
                 + (" · this week" if w == current else ""))
        with st.expander(label, expanded=(w == current), icon=":material/check_circle:" if n_done == len(ws) else None):
            for s in ws:
                _session_row(s, today, statuses)

    _edit_plan(plan, sessions)

    with st.expander("What the efforts mean", icon=":material/help:"):
        st.markdown("\n".join(f"- **{name}:** {desc}" for name, desc in training.KINDS.values()))
        st.caption("Distances and paces are a guide. If something hurts (more than normal tiredness), rest and move "
                   "the session; never squeeze two hard days together to catch up.")

    placed = sum(1 for s in sessions if s["block_id"])
    tt, over = st.columns(2)
    with tt.popover("Timetable", icon=":material/calendar_view_week:"):
        st.write(f"{placed} of {len(sessions)} sessions are on your timetable. Move or change them there, "
                 "or here with each session's ⋯.")
        times = _times()
        times["weekday"] = _time_input("Weekday sessions at", times["weekday"], "tr_tt_weekday")
        times["weekend"] = _time_input("Long runs and weekends at", times["weekend"], "tr_tt_weekend")
        if st.button("Put sessions on my timetable" if not placed else "Re-place them at these times",
                     type="primary", icon=":material/event_available:"):
            tools.put_plan_on_timetable(times)
            st.rerun()
        if placed and st.button("Take them off my timetable", icon=":material/event_busy:"):
            tools.take_plan_off_timetable()
            st.rerun()

    with over.popover("Start over", icon=":material/restart_alt:"):
        st.write("Delete this plan (and what you've logged in it) so you can create a new one.")
        if st.button("Delete plan", type="primary", icon=":material/delete:"):
            store.delete_plan(plan["id"])
            st.rerun()

    st.divider()
    _gym_log()


# ---------------------------------------------------------------------------
# Gym log: sessions, each with exercises (weight, sets, reps)
# ---------------------------------------------------------------------------

GYM_COLUMNS = {
    "exercise": st.column_config.TextColumn("Exercise", required=True, width="medium"),
    "weight_kg": st.column_config.NumberColumn("Weight (kg)", min_value=0.0, step=0.5, format="%g"),
    "sets": st.column_config.NumberColumn("Sets", min_value=0, step=1, format="%d"),
    "reps": st.column_config.NumberColumn("Reps", min_value=0, step=1, format="%d"),
}
GYM_ORDER = ["exercise", "weight_kg", "sets", "reps"]


def _rows(df):
    return [r for r in df.to_dict("records") if str(r.get("exercise") or "").strip()]


def _volume(exercises):
    """Total kg lifted: weight × sets × reps."""
    return sum((x["weight_kg"] or 0) * (x["sets"] or 0) * (x["reps"] or 0) for x in exercises)


def _tick_strength(day):
    """Logging a gym session ticks off that day's strength session in the plan, if there is one."""
    plan = store.active_plan()
    if plan:
        for s in store.plan_sessions(plan["id"]):
            if s["date"] == day and s["kind"] == "strength" and not s["done"]:
                store.update_session(s["id"], done=True)
                return s["title"]
    return None


def _gym_log():
    import pandas as pd
    st.subheader("Gym log", anchor=False)
    past = store.gym_sessions(limit=30)

    with st.expander("Log a gym session", icon=":material/fitness_center:", expanded=not past):
        a, b = st.columns([1, 2])
        day = a.date_input("Day", value=store.local_today(), format="DD/MM/YYYY", key="gym_new_day")
        title = b.text_input("Session", placeholder="e.g. Push day, Legs", key="gym_new_title")
        names = list(dict.fromkeys(s["title"] for s in past))
        start = st.selectbox("Start from", ["Blank"] + [f"Last {n}" for n in names], key="gym_new_from",
                             help="Copies the exercises (and weights) from the last session with that name.")
        rows = [{"exercise": "", "weight_kg": None, "sets": 3, "reps": 10}]
        if start != "Blank":
            last = next(s for s in past if s["title"] == start[len("Last "):])
            rows = last["exercises"] or rows
        table = st.data_editor(pd.DataFrame(rows, columns=GYM_ORDER), num_rows="dynamic", hide_index=True,
                               column_config=GYM_COLUMNS, column_order=GYM_ORDER, width="stretch",
                               key=f"gym_new_table_{start}")
        notes = st.text_input("Notes (optional)", key="gym_new_notes", placeholder="How did it feel?")
        if st.button("Save session", type="primary", icon=":material/save:"):
            exercises = _rows(table)
            if not exercises:
                st.error("Add at least one exercise.")
            else:
                store.save_gym_session(day.isoformat(), title or (start[len("Last "):] if start != "Blank" else "Gym"),
                                       exercises, notes)
                ticked = _tick_strength(day.isoformat())
                for k in [k for k in st.session_state if k.startswith("gym_new_")]:
                    del st.session_state[k]
                st.toast("Saved." + (f" Ticked off {ticked} in your plan." if ticked else ""), icon=":material/check_circle:")
                st.rerun()

    if not past:
        st.caption("No gym sessions yet.")
        return
    for s in past:
        d = store._as_date(s["date"])
        vol = _volume(s["exercises"])
        label = (f"{d:%a} {d.day} {d:%b} · {s['title']} · {len(s['exercises'])} exercise"
                 f"{'s' * (len(s['exercises']) != 1)}" + (f" · {vol:,.0f} kg lifted" if vol else ""))
        with st.expander(label):
            if s["notes"]:
                st.caption(s["notes"])
            table = st.data_editor(pd.DataFrame(s["exercises"], columns=GYM_ORDER), num_rows="dynamic", hide_index=True,
                                   column_config=GYM_COLUMNS, column_order=GYM_ORDER, width="stretch",
                                   key=f"gym_{s['id']}")
            save, delete = st.columns(2)
            if save.button("Save changes", key=f"gym_save_{s['id']}", width="stretch"):
                store.save_gym_session(s["date"], s["title"], _rows(table), s["notes"], session_id=s["id"])
                st.rerun()
            if delete.button("Delete session", key=f"gym_del_{s['id']}", icon=":material/delete:", width="stretch"):
                store.delete_gym_session(s["id"])
                st.rerun()


KM_COLOUR = "#22C55E"


def km_goals(today=None):
    """
    Km run against the training plan, as goals: this week, this month and the whole plan.
    Each: (title, when, run_km, planned_km or None). Runs are Strava plus ticked-off training runs.
    """
    today = today or store.local_today()
    plan = store.active_plan()
    sessions = [s for s in store.plan_sessions(plan["id"]) if s["kind"] != "strength"] if plan else []
    week0 = today - timedelta(days=today.weekday())
    week1, month0 = week0 + timedelta(days=6), today.replace(day=1)
    month1 = (month0 + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    first = min(week0, month0, date.fromisoformat(plan["start_date"]) if plan else month0)
    runs = store.runs(first.isoformat(), today.isoformat())

    def run(a, b):
        return sum(r["distance_km"] or 0 for r in runs if a.isoformat() <= r["date"] <= b.isoformat())

    def planned(a, b):
        km = sum(s["distance_km"] or 0 for s in sessions if a.isoformat() <= s["date"] <= b.isoformat())
        return km or None

    rows = [("This week", f"{week0.day} {week0:%b} to {week1.day} {week1:%b}", run(week0, week1), planned(week0, week1)),
            ("This month", f"{today:%B}", run(month0, month1), planned(month0, month1))]
    if plan:
        p0, p1 = date.fromisoformat(plan["start_date"]), date.fromisoformat(plan["race_date"])
        rows.append((plan["name"], f"to race day {p1.day} {p1:%b}", run(p0, p1), planned(p0, p1)))
    return rows


def render_home_km():
    """Km run as goals under Goals on Home: this week, this month and the whole plan, against the plan's km."""
    from venato.ui import goals
    head, link = st.columns([4, 1], vertical_alignment="center")
    head.markdown("**Km run**")
    link.button("Training", key="home_km_training", type="tertiary", on_click=_go_to_training)
    rows = []
    for title, when, run_km, plan_km in km_goals():
        if plan_km:
            rows.append(goals.bar_row(title, when, f"{run_km:.1f} / {plan_km:g} km", run_km / plan_km, KM_COLOUR))
        else:
            rows.append(goals.bar_row(title, when, f"{run_km:.1f} km", 0, KM_COLOUR))
    st.html(goals.home_css(KM_COLOUR) + f'<div class="hg">{"".join(rows)}</div>')
    if not store.active_plan():
        st.caption("Set up a training plan on the Training page and these become goals that grow week by week.")


def _go_to_training():
    st.session_state["page"] = PAGE


def render_home():
    """Today's training session(s) on Home, to tick off."""
    plan = store.active_plan()
    if not plan:
        return
    today = store.local_today().isoformat()
    todays = [s for s in store.plan_sessions(plan["id"]) if s["date"] == today]
    if not todays:
        return
    st.markdown("**Today's training**")
    for s in todays:
        key = f"tr_home_{s['id']}"
        km = f" · {_km(s['distance_km'])}" if s["distance_km"] else ""
        st.session_state[key] = s["done"]      # always what's saved (it may have been ticked on Training)
        st.checkbox(f"{s['title']}{km}", key=key, on_change=_toggle, args=(s["id"], key), help=s["details"])
