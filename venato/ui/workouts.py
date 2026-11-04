"""The Workouts page (log, history, progress, plans, exercises) and its Home widget.
The data and the maths are in venato/blocks/workouts.py."""

from datetime import timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from venato import store
from venato import undo
from venato.blocks import workouts as wk

NEW_EX = "+ New exercise"
CURRENT = "wk_current"


def _metrics(today):
    week0 = store.week_start_of(today)
    week = wk.workouts(week0, today)
    vol = wk.weekly_volume(week0, today)
    a, b, c = st.columns(3)
    a.metric("Workouts this week", len(week))
    b.metric("Working sets", sum(v["sets"] for v in vol.values()))
    c.metric("Volume", f"{wk.kg_out(sum(v['tonnage'] for v in vol.values())) or 0:,.0f} {wk.units()[0]}",
             help="Weight × reps of this week's working sets")


# --- Log ---

def _choose_workout(today):
    todays = wk.workouts(today - timedelta(days=0), today)
    wid = st.session_state.get(CURRENT)
    if wid and not wk.get_workout(wid):
        wid = None
    if not wid and todays:
        wid = todays[0]["id"]
    a, b, c = st.columns([2, 2, 2], vertical_alignment="bottom")
    with a.popover("New workout", icon=":material/add:", width="stretch"):
        with st.form("wk_new", border=False):
            day = st.date_input("Day", today)
            title = st.text_input("Title", placeholder="e.g. Push day")
            if st.form_submit_button("Start", type="primary"):
                st.session_state[CURRENT] = wk.add_workout(day, title or "Workout")
                st.rerun()
    plan_list = wk.plans()
    with b.popover("Start a plan", icon=":material/list_alt:", width="stretch", disabled=not plan_list):
        for p in plan_list:
            if st.button(p["name"], key=f"wk_plan_go_{p['id']}", width="stretch"):
                st.session_state[CURRENT] = wk.start_from_plan(p["id"], today)
                st.rerun()
    if c.button("Today's workout", key="wk_today", width="stretch", icon=":material/today:"):
        st.session_state[CURRENT] = wk.workout_on(today, "Workout")
        st.rerun()
    return wid


def _add_sets_form(wid):
    names = [e["name"] for e in wk.exercises()]
    w_unit, d_unit = wk.units()
    with st.form(f"wk_add_{wid}", clear_on_submit=False, border=True):
        st.markdown("**Add sets**")
        a, b = st.columns([3, 2])
        choice = a.selectbox("Exercise", names + [NEW_EX], key=f"wk_ex_{wid}")
        new_name = b.text_input("New exercise name", key=f"wk_newname_{wid}",
                                placeholder="only for + New exercise")
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        count = c1.number_input("Sets", 1, 50, 3, key=f"wk_n_{wid}")
        reps = c2.number_input("Reps", 0, 1000, 8, key=f"wk_reps_{wid}")
        weight = c3.number_input(f"Weight ({w_unit})", 0.0, 2000.0, 0.0, step=2.5, key=f"wk_w_{wid}")
        dist = c4.number_input(f"Distance ({d_unit})", 0.0, 1000.0, 0.0, step=0.5, key=f"wk_d_{wid}")
        mins = c5.number_input("Minutes", 0.0, 1440.0, 0.0, step=1.0, key=f"wk_m_{wid}")
        warm = c6.checkbox("Warm-up", key=f"wk_warm_{wid}")
        if st.form_submit_button("Add", type="primary", icon=":material/add:"):
            try:
                if choice == NEW_EX:
                    kind = "cardio" if dist else "timed" if mins and not reps else "weights" if weight else "bodyweight"
                    ex = wk.add_exercise(new_name, kind)
                else:
                    ex = wk.find_exercise(choice)
                wk.add_sets(wid, ex["id"], count, reps or None, wk.kg_in(weight) if weight else None,
                            wk.km_in(dist) if dist else None, int(mins * 60) if mins else None, warm)
                st.rerun()
            except wk.WorkoutError as e:
                st.error(str(e))


def _apply_set_edits(key, ids):
    state = st.session_state.get(key) or {}
    for i in state.get("deleted_rows", []):
        if int(i) < len(ids):
            wk.delete_set(ids[int(i)])
    for i, ch in state.get("edited_rows", {}).items():
        if int(i) >= len(ids):
            continue
        f = {}
        for col, field, conv in (("Reps", "reps", lambda v: None if v is None else int(v)),
                                 ("Weight", "weight", wk.kg_in), ("Distance", "distance", wk.km_in),
                                 ("Minutes", "seconds", lambda v: None if v in (None, "") else int(float(v) * 60)),
                                 ("Warm-up", "warmup", lambda v: int(bool(v))), ("RPE", "rpe", lambda v: v)):
            if col in ch:
                f[field] = conv(ch[col])
        wk.update_set(ids[int(i)], **f)


def _sets_table(wid):
    sets = wk.sets_of(wid)
    if not sets:
        st.caption("No sets yet: add some above, or type e.g. \"bench 3x8 at 60\" in the chat box.")
        return
    w_unit, d_unit = wk.units()
    df = pd.DataFrame([{
        "Exercise": s["exercise"], "Reps": s["reps"], "Weight": wk.kg_out(s["weight"]),
        "Distance": wk.km_out(s["distance"]), "Minutes": None if s["seconds"] is None else round(s["seconds"] / 60, 1),
        "Warm-up": bool(s["warmup"]), "RPE": s["rpe"],
        "Est. 1RM": wk.kg_out(wk.one_rep_max(s["weight"], s["reps"])) if not s["warmup"] else None,
    } for s in sets])
    key = f"wk_sets_{wid}"
    st.data_editor(
        df, key=key, on_change=_apply_set_edits, args=(key, [s["id"] for s in sets]), num_rows="delete",
        hide_index=True, width="stretch",
        column_config={
            "Exercise": st.column_config.TextColumn(disabled=True),
            "Weight": st.column_config.NumberColumn(f"Weight ({w_unit})", min_value=0, step=0.5),
            "Distance": st.column_config.NumberColumn(f"Distance ({d_unit})", min_value=0, step=0.1),
            "Minutes": st.column_config.NumberColumn(min_value=0, step=0.5),
            "RPE": st.column_config.NumberColumn(min_value=1, max_value=10, step=0.5),
            "Est. 1RM": st.column_config.NumberColumn(f"Est. 1RM ({w_unit})", disabled=True, format="%.1f"),
        })


def _workout_details(wid):
    w = wk.get_workout(wid)
    a, b, c, d = st.columns([3, 2, 1, 1])
    title = a.text_input("Title", w["title"], key=f"wk_title_{wid}")
    day = b.date_input("Day", store._as_date(w["date"]), key=f"wk_day_{wid}")
    minutes = c.number_input("Minutes", 0, 1440, int(w["minutes"] or 0), key=f"wk_min_{wid}")
    rpe = d.number_input("Effort (1-10)", 0, 10, int(w["rpe"] or 0), key=f"wk_rpe_{wid}")
    notes = st.text_input("Notes", w["notes"] or "", key=f"wk_notes_{wid}")
    new = {"title": title.strip() or "Workout", "date": day.isoformat(), "minutes": minutes or None,
           "rpe": rpe or None, "notes": notes.strip() or None}
    if any(new[k] != w[k] for k in new):
        wk.update_workout(wid, **new)


def _log_tab(today):
    wid = _choose_workout(today)
    if not wid:
        st.info("Start a workout above, or start one of your plans.")
        return
    w = wk.get_workout(wid)
    st.subheader(f"{w['title']} · {store._as_date(w['date']):%a %-d %b}", anchor=False)
    _workout_details(wid)
    _add_sets_form(wid)
    _sets_table(wid)
    a, b = st.columns(2)
    with a.popover("Save as plan", icon=":material/bookmark_add:"):
        name = st.text_input("Plan name", w["title"], key=f"wk_planname_{wid}")
        if st.button("Save", key=f"wk_plansave_{wid}", type="primary"):
            try:
                wk.save_plan_from(wid, name)
                st.success(f"Saved the plan {name}.")
            except wk.WorkoutError as e:
                st.error(str(e))
    if b.button("Delete this workout", key=f"wk_del_{wid}", icon=":material/delete:"):
        undo.checkpoint(f"Deleted the workout {w['title']}")
        wk.delete_workout(wid)
        st.session_state.pop(CURRENT, None)
        st.rerun()


# --- History, progress, plans, exercises ---

def _history_tab(today):
    rows = wk.workouts(today - timedelta(days=180), today)
    if not rows:
        st.caption("No workouts in the last 6 months.")
    for w in rows:
        label = f"{store._as_date(w['date']):%a %-d %b} · {w['title']}" + (f" · {w['source']}" if w["source"] != "manual" else "")
        with st.expander(label):
            st.write(wk.summary(w["id"]) or "No sets.")
            bits = [f"{w['minutes']:.0f} min" if w["minutes"] else "", f"effort {w['rpe']:g}/10" if w["rpe"] else "",
                    w["notes"] or ""]
            if any(bits):
                st.caption(" · ".join(b for b in bits if b))
            if st.button("Open", key=f"wk_open_{w['id']}"):
                st.session_state[CURRENT] = w["id"]
                st.session_state["wk_tab_hint"] = True
                st.toast("Opened in the Log tab.")


def _progress_tab(today):
    w_unit, d_unit = wk.units()
    pbs = wk.personal_bests()
    if not pbs:
        st.caption("Log some workouts to see progress and personal bests.")
        return
    names = sorted(pbs)
    name = st.selectbox("Exercise", names, key="wk_prog_ex")
    ex = wk.find_exercise(name)
    rows = wk.progress(ex["id"])
    if rows:
        df = pd.DataFrame(rows, columns=["date", "orm", "top", "reps", "km"])
        df["date"] = pd.to_datetime(df["date"])
        if ex["kind"] == "cardio":
            df["Distance"] = df["km"].map(wk.km_out)
            fig = px.line(df, x="date", y="Distance", markers=True, title=f"{name}: distance ({d_unit})")
        elif df["top"].notna().any():
            df["Est. 1RM"] = df["orm"].map(wk.kg_out)
            df["Top set"] = df["top"].map(wk.kg_out)
            fig = px.line(df, x="date", y=["Est. 1RM", "Top set"], markers=True, title=f"{name} ({w_unit})",
                          labels={"value": w_unit, "variable": ""})
        else:
            fig = px.bar(df, x="date", y="reps", title=f"{name}: total reps", labels={"reps": "Reps"})
        fig.update_xaxes(title=None, tickformat="%-d %b")
        st.plotly_chart(fig, width="stretch")
    st.markdown("**Personal bests**")
    table = []
    for n in names:
        pb = pbs[n]
        table.append({"Exercise": n,
                      f"Heaviest ({w_unit})": wk.kg_out(pb["heaviest"][0]) if "heaviest" in pb else None,
                      f"Est. 1RM ({w_unit})": wk.kg_out(pb["best_1rm"][0]) if "best_1rm" in pb else None,
                      "Most reps": pb["most_reps"][0] if "most_reps" in pb else None,
                      f"Longest ({d_unit})": wk.km_out(pb["longest_km"][0]) if "longest_km" in pb else None})
    st.dataframe(pd.DataFrame(table), hide_index=True, width="stretch")
    st.markdown("**Sets per muscle group**")
    week0 = store.week_start_of(today)
    this, last = wk.weekly_volume(week0, today), wk.weekly_volume(week0 - timedelta(days=7), week0 - timedelta(days=1))
    vol = [{"Muscle": m, "Week": "This week", "Sets": v["sets"]} for m, v in this.items()] + \
          [{"Muscle": m, "Week": "Last week", "Sets": v["sets"]} for m, v in last.items()]
    if vol:
        fig = px.bar(pd.DataFrame(vol), x="Muscle", y="Sets", color="Week", barmode="group")
        fig.update_xaxes(title=None)
        st.plotly_chart(fig, width="stretch")


def _plans_tab():
    ps = wk.plans()
    if not ps:
        st.caption("No plans yet. Log a workout, then \"Save as plan\" to reuse it.")
    for p in ps:
        with st.container(border=True):
            a, b, c = st.columns([5, 1, 1], vertical_alignment="center")
            items = wk.plan_items(p["id"])
            a.markdown(f"**{p['name']}**  \n" + ", ".join(
                f"{i['exercise']} {i['sets']}×{i['reps'] or '-'}" + (f" @ {wk.weight_text(i['weight'])}" if i["weight"] else "")
                for i in items))
            if b.button("Start", key=f"wk_pstart_{p['id']}", type="primary"):
                st.session_state[CURRENT] = wk.start_from_plan(p["id"])
                st.toast(f"Started {p['name']}: it's in the Log tab.")
            if c.button("", icon=":material/delete:", key=f"wk_pdel_{p['id']}", help="Delete this plan"):
                undo.checkpoint(f"Deleted the plan {p['name']}")
                wk.delete_plan(p["id"])
                st.rerun()


def _exercises_tab():
    exs = wk.exercises()
    st.dataframe(pd.DataFrame([{"Exercise": e["name"], "Type": e["kind"], "Muscle": e["muscle"] or ""} for e in exs]),
                 hide_index=True, width="stretch", height=300)
    with st.form("wk_ex_add", clear_on_submit=True):
        a, b, c = st.columns(3)
        name = a.text_input("New exercise")
        kind = b.selectbox("Type", wk.KINDS)
        muscle = c.selectbox("Muscle group", ("",) + wk.MUSCLES)
        if st.form_submit_button("Add exercise"):
            try:
                wk.add_exercise(name, kind, muscle or None)
                st.rerun()
            except wk.WorkoutError as e:
                st.error(str(e))


def _settings_tab():
    w, d = wk.units()
    a, b = st.columns(2)
    nw = a.segmented_control("Weight", ["kg", "lb"], default=w, key="wk_unit_w")
    nd = b.segmented_control("Distance", ["km", "mi"], default=d, key="wk_unit_d")
    if (nw or w, nd or d) != (w, d):
        wk.save_units(nw or w, nd or d)
        st.rerun()
    habits = [n for _, n in store.get_habits()]
    current = (store.load_settings().get("workouts") or {}).get("habit")
    opts = ["(none)"] + habits
    pick = st.selectbox("Tick this habit when you log a workout", opts,
                        index=opts.index(current) if current in opts else 0, key="wk_habit")
    if (None if pick == "(none)" else pick) != current:
        wk.set_habit_link(None if pick == "(none)" else pick)


def render_page():
    st.title("Workouts")
    today = store.local_today()
    _metrics(today)
    tabs = st.tabs(["Log", "History", "Progress", "Plans", "Exercises", "Settings"])
    with tabs[0]:
        _log_tab(today)
    with tabs[1]:
        _history_tab(today)
    with tabs[2]:
        _progress_tab(today)
    with tabs[3]:
        _plans_tab()
    with tabs[4]:
        _exercises_tab()
    with tabs[5]:
        _settings_tab()


def render_home():
    today = store.local_today()
    week = wk.workouts(store.week_start_of(today), today)
    st.markdown("**Workouts**")
    last = wk.workouts(today - timedelta(days=60), today)[:1]
    text = f"{len(week)} this week"
    if last:
        w = last[0]
        text += f" · last: {store._as_date(w['date']):%a %-d %b}, {w['title']}"
        detail = wk.summary(w["id"])
        if detail:
            text += f" ({detail[:80]}{'…' if len(detail) > 80 else ''})"
    st.caption(text)
