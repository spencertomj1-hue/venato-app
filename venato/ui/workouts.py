"""The Workouts page (log, history, progress, plans, exercises) and its Home widget.
The data and the maths are in venato/blocks/workouts.py."""

from datetime import timedelta

import altair as alt
import pandas as pd
import streamlit as st

from venato import store
from venato import undo
from venato.blocks import workouts as wk
from venato.ui import kit

NEW_EX = "+ New exercise"
CURRENT = "wk_current"


def _metrics(today):
    week0 = store.week_start_of(today)
    last0 = week0 - timedelta(days=7)
    week, prev = wk.workouts(week0, today), wk.workouts(last0, last0 + (today - week0))
    vol, pvol = wk.weekly_volume(week0, today), wk.weekly_volume(last0, last0 + (today - week0))
    sets, psets = sum(v["sets"] for v in vol.values()), sum(v["sets"] for v in pvol.values())
    ton = wk.kg_out(sum(v["tonnage"] for v in vol.values())) or 0
    pton = wk.kg_out(sum(v["tonnage"] for v in pvol.values())) or 0
    recent = wk.workouts(today - timedelta(days=60), today)[:1]
    if recent:
        ago = (today - store._as_date(recent[0]["date"])).days
        last = "Today" if ago == 0 else "Yesterday" if ago == 1 else f"{ago} days ago"
    else:
        last = "–"

    def delta(now, before, unit=""):
        if not before and not now:
            return None
        d = now - before
        return f"{'+' if d >= 0 else '-'}{abs(d):,.0f}{unit} vs this point last week"

    kit.stats([
        {"label": "Workouts this week", "value": str(len(week)), "delta": delta(len(week), len(prev))},
        {"label": "Working sets", "value": str(sets), "delta": delta(sets, psets)},
        {"label": "Volume", "value": f"{ton:,.0f} {wk.units()[0]}", "delta": delta(ton, pton, f" {wk.units()[0]}"),
         "help": "Weight × reps of this week's working sets"},
        {"label": "Last workout", "value": last,
         "delta": recent[0]["title"] if recent else None, "delta_color": "off", "delta_arrow": "off"},
    ])


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
        choice = st.selectbox("Exercise", names + [NEW_EX], key=f"wk_ex_{wid}")
        new_name = st.text_input("New exercise name", key=f"wk_newname_{wid}",
                                 placeholder="only for + New exercise")
        c1, c2, c3 = st.columns(3)
        count = c1.number_input("Sets", 1, 50, 3, key=f"wk_n_{wid}")
        reps = c2.number_input("Reps", 0, 1000, 8, key=f"wk_reps_{wid}")
        weight = c3.number_input(f"Weight ({w_unit})", 0.0, 2000.0, 0.0, step=2.5, key=f"wk_w_{wid}")
        c4, c5, c6 = st.columns(3, vertical_alignment="bottom")
        dist = c4.number_input(f"Distance ({d_unit})", 0.0, 1000.0, 0.0, step=0.5, key=f"wk_d_{wid}")
        mins = c5.number_input("Minutes", 0.0, 1440.0, 0.0, step=1.0, key=f"wk_m_{wid}")
        warm = c6.checkbox("Warm-up", key=f"wk_warm_{wid}")
        if st.form_submit_button("Add", type="primary", icon=":material/add:", width="stretch"):
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
    shown = [c for c in df.columns if c not in ("Distance", "Minutes") or df[c].notna().any()]
    st.data_editor(
        df, key=key, on_change=_apply_set_edits, args=(key, [s["id"] for s in sets]), num_rows="delete",
        hide_index=True, width="stretch", column_order=shown,
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
        kit.empty("Start a workout above, or start one of your plans.", ":material/fitness_center:")
        return
    w = wk.get_workout(wid)
    st.subheader(f"{w['title']} · {store.fmt_day(store._as_date(w['date']), '%a %-d %b')}", anchor=False)
    summary = wk.summary(wid)
    if summary:
        names = [e["name"] for e in wk.exercises()]
        colours = kit.colours(names)
        kit.pills([(part, colours.get(next((n for n in names if part.startswith(n)), ""), kit.PALETTE[0]))
                   for part in summary.split(", ")])
    a, b = st.columns([3, 2])
    with a, kit.card("Sets"):
        _sets_table(wid)
    with b:
        _add_sets_form(wid)
    with st.expander("Details", icon=":material/edit_note:"):
        _workout_details(wid)
    a, b, _ = st.columns([1, 1, 2])
    with a.popover("Save as plan", icon=":material/bookmark_add:", width="stretch"):
        name = st.text_input("Plan name", w["title"], key=f"wk_planname_{wid}")
        if st.button("Save", key=f"wk_plansave_{wid}", type="primary"):
            try:
                wk.save_plan_from(wid, name)
                st.success(f"Saved the plan {name}.")
            except wk.WorkoutError as e:
                st.error(str(e))
    with b.popover("Delete workout", icon=":material/delete:", width="stretch"):
        st.warning(f"Delete {w['title']} and its sets? (Undo can bring it back.)")
        if st.button("Delete", key=f"wk_del_{wid}", type="primary"):
            undo.checkpoint(f"Deleted the workout {w['title']}")
            wk.delete_workout(wid)
            st.session_state.pop(CURRENT, None)
            st.rerun()


# --- History, progress, plans, exercises ---

def _history_tab(today):
    rows = wk.workouts(today - timedelta(days=180), today)
    if not rows:
        kit.empty("No workouts in the last 6 months.", ":material/history:")
        return
    first = store.week_start_of(today) - timedelta(weeks=11)
    weeks = [first + timedelta(weeks=i) for i in range(12)]
    counts = {w: 0 for w in weeks}
    for w in rows:
        k = store.week_start_of(store._as_date(w["date"]))
        if k in counts:
            counts[k] += 1
    with kit.card("Workouts per week", stretch=False):
        per_week = pd.DataFrame({"Week of": pd.to_datetime(weeks), "Workouts": list(counts.values())})
        kit.show(kit.bar_chart(per_week, "Week of", "Workouts", height=200, size=18,
                               x_axis=alt.Axis(format=kit.DAY_FORMAT, labelOverlap=True, grid=False, labelAngle=0),
                               y_axis=alt.Axis(tickMinStep=1, format="d", title=None)))
    cols = st.columns(3)
    for i, w in enumerate(rows[:30]):
        with cols[i % 3], st.container(border=True, height="stretch"):
            day = store._as_date(w["date"])
            kit.html(f"<div style='display:flex;gap:12px;align-items:center'>{kit.date_badge(day)}<div>"
                     f"<b>{w['title']}</b><br><span style='opacity:.7;font-size:.85rem'>{day:%A}"
                     + (f" · {w['minutes']:.0f} min" if w["minutes"] else "")
                     + (f" · effort {w['rpe']:g}/10" if w["rpe"] else "")
                     + (f" · {w['source']}" if w["source"] != "manual" else "") + "</span></div></div>")
            st.caption(wk.summary(w["id"]) or "No sets.")
            if w["notes"]:
                st.caption(w["notes"])
            if st.button("Open", key=f"wk_open_{w['id']}", icon=":material/arrow_forward:", width="stretch"):
                st.session_state[CURRENT] = w["id"]
                st.toast("Opened in the Log tab.")


def _progress_tab(today):
    w_unit, d_unit = wk.units()
    pbs = wk.personal_bests()
    if not pbs:
        kit.empty("Log some workouts to see progress and personal bests.", ":material/trending_up:")
        return
    names = sorted(pbs)
    a, _ = st.columns([1, 2])
    name = a.selectbox("Exercise", names, key="wk_prog_ex")
    ex = wk.find_exercise(name)
    pb = pbs[name]
    tiles = []
    if "best_1rm" in pb:
        tiles.append({"label": "Best est. 1RM", "value": f"{wk.kg_out(pb['best_1rm'][0]):,.1f} {w_unit}",
                      "delta": f"{store.fmt_day(store._as_date(pb['best_1rm'][1]), '%-d %b %Y')}", "delta_color": "off",
                      "delta_arrow": "off"})
    if "heaviest" in pb:
        tiles.append({"label": "Heaviest set", "value": f"{wk.kg_out(pb['heaviest'][0]):,.1f} {w_unit}",
                      "delta": f"{store.fmt_day(store._as_date(pb['heaviest'][1]), '%-d %b %Y')}", "delta_color": "off",
                      "delta_arrow": "off"})
    if "most_reps" in pb:
        tiles.append({"label": "Most reps in a set", "value": str(pb["most_reps"][0])})
    if "longest_km" in pb:
        tiles.append({"label": "Longest", "value": f"{wk.km_out(pb['longest_km'][0]):g} {d_unit}"})
    if tiles:
        kit.stats(tiles, per_row=4)
    rows = wk.progress(ex["id"])
    a, b = st.columns([3, 2])
    with a, kit.card(f"{name} over time"):
        if rows:
            df = pd.DataFrame(rows, columns=["date", "orm", "top", "reps", "km"])
            df["date"] = pd.to_datetime(df["date"])
            x_axis = alt.Axis(format=kit.DAY_FORMAT, labelOverlap=True, grid=False, labelAngle=0)
            if ex["kind"] == "cardio":
                df["Distance"] = df["km"].map(wk.km_out)
                chart = kit.line_chart(df, "date", ["Distance"], palette={"Distance": kit.colours(range(3))[2]}, height=300,
                                       x_axis=x_axis, y_axis=alt.Axis(labelExpr=f"datum.value + ' {d_unit}'"))
            elif df["top"].notna().any():
                df["Est. 1RM"] = df["orm"].map(wk.kg_out)
                df["Top set"] = df["top"].map(wk.kg_out)
                chart = kit.line_chart(df, "date", ["Est. 1RM", "Top set"], height=300, x_axis=x_axis,
                                       palette=kit.colours(["Est. 1RM", "Top set"]),
                                       y_axis=alt.Axis(labelExpr=f"datum.value + ' {w_unit}'"))
            else:
                df["Total reps"] = df["reps"]
                chart = kit.bar_chart(df, "date", "Total reps", height=300, size=14, x_axis=x_axis)
            kit.show(chart)
        else:
            kit.empty("No working sets of this one yet.")
    with b, kit.card("Sets per muscle group", "This week against last week"):
        week0 = store.week_start_of(today)
        this = wk.weekly_volume(week0, today)
        last = wk.weekly_volume(week0 - timedelta(days=7), week0 - timedelta(days=1))
        muscles = sorted(set(this) | set(last), key=lambda m: -(this.get(m, {}).get("sets", 0)))
        if muscles:
            vol = pd.DataFrame([{"Muscle": m, "Week": label, "Sets": data.get(m, {}).get("sets", 0)}
                                for m in muscles for label, data in (("Last week", last), ("This week", this))])
            chart = kit.bar_chart(vol, "Muscle", "Sets", color="Week", horizontal=True,
                                  height=max(200, 40 * len(muscles) + 60),
                                  palette={"Last week": kit.muted(), "This week": kit.colours([0])[0]},
                                  y_axis=alt.Axis(tickMinStep=1, format="d"))
            kit.show(chart)
        else:
            kit.empty("No sets in the last two weeks.")
    with kit.card("Personal bests", stretch=False):
        table = []
        for n in names:
            p = pbs[n]
            table.append({"Exercise": n,
                          f"Heaviest ({w_unit})": wk.kg_out(p["heaviest"][0]) if "heaviest" in p else None,
                          f"Est. 1RM ({w_unit})": wk.kg_out(p["best_1rm"][0]) if "best_1rm" in p else None,
                          "Most reps": p["most_reps"][0] if "most_reps" in p else None,
                          f"Longest ({d_unit})": wk.km_out(p["longest_km"][0]) if "longest_km" in p else None})
        kit.table(table, numbers={f"Heaviest ({w_unit})": "%.1f", f"Est. 1RM ({w_unit})": "%.1f"})


def _plans_tab():
    ps = wk.plans()
    if not ps:
        kit.empty("No plans yet. Log a workout, then \"Save as plan\" to reuse it.", ":material/list_alt:")
        return
    cols = st.columns(3)
    for i, p in enumerate(ps):
        with cols[i % 3], st.container(border=True, height="stretch"):
            st.markdown(f"**{p['name']}**")
            for it in wk.plan_items(p["id"]):
                st.markdown(f"- {it['exercise']} · {it['sets']}×{it['reps'] or '-'}"
                            + (f" @ {wk.weight_text(it['weight'])}" if it["weight"] else ""))
            a, b = st.columns([3, 1])
            if a.button("Start", key=f"wk_pstart_{p['id']}", type="primary", icon=":material/play_arrow:",
                        width="stretch"):
                st.session_state[CURRENT] = wk.start_from_plan(p["id"])
                st.toast(f"Started {p['name']}: it's in the Log tab.")
            with b.popover("", icon=":material/delete:", width="stretch", help="Delete this plan"):
                st.warning(f"Delete the plan {p['name']}?")
                if st.button("Delete", key=f"wk_pdel_{p['id']}", type="primary"):
                    undo.checkpoint(f"Deleted the plan {p['name']}")
                    wk.delete_plan(p["id"])
                    st.rerun()


def _exercises_tab():
    exs = wk.exercises()
    kit.table([{"Exercise": e["name"], "Type": e["kind"], "Muscle": e["muscle"] or ""} for e in exs], height=300)
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
        text += f" · last: {store.fmt_day(store._as_date(w['date']), '%a %-d %b')}, {w['title']}"
        detail = wk.summary(w["id"])
        if detail:
            text += f" ({detail[:80]}{'…' if len(detail) > 80 else ''})"
    st.caption(text)
