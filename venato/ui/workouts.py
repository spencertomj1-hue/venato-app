"""The Workouts page (log, history, progress, plans, exercises) and its Home widget.
The data and the maths are in venato/blocks/workouts.py."""

from datetime import timedelta

import altair as alt
import pandas as pd
import streamlit as st

from venato import regional
from venato import store
from venato import tools
from venato import undo
from venato.blocks import workouts as wk
from venato.ui import kit

CURRENT = "wk_current"
UPLOAD_PENDING = "wk_upload_pending"      # a tools.Pending preview of an uploaded plan, waiting for Confirm
EXAMPLE = """Week 1
Monday - Push
Bench press 3x8 @ 60kg
Overhead press 3x10 @ 40kg

Legs
Squat 5x5 @ 100kg
Plank 3x45s

Week 2
Monday - Push
Bench press 3x8 @ 62.5kg
Overhead press 3x10 @ 42.5kg

Legs
Squat 5x5 @ 105kg
Plank 3x50s"""
CLAUDE_PROMPT = """Write me a workout plan with progressive overload. Reply with ONLY the plan, in exactly this plain-text format (no tables, no bold, no headings, no notes or explanations), because an app reads it line by line:

- Start each week with a line on its own: Week 1, Week 2, Week 3, ...
- Write out every week in full, with that week's own weights, sets and reps (increase them week by week; add a deload week if it suits the plan).
- Inside a week, start each workout with a line naming it. If it must be on a set day, put the day first: Monday - Push. Otherwise just the name: Legs.
- Use the same workout names every week (Push in week 1 is Push in week 2).
- Then one exercise per line: name, sets x reps, then @ and the weight with its unit:
  Bench press 3x8 @ 60kg
  Pull-up 3x8                (bodyweight: no weight)
  Plank 3x45s                (timed: seconds straight after the number)
  Run 5 km                   (cardio: a distance, or minutes like 30 min)
- One number for reps (8, not 8-10). No warm-up lines, no rest times, no comments.
- Leave a blank line between workouts.

Example of the format:
Week 1
Monday - Push
Bench press 3x8 @ 60kg
Overhead press 3x10 @ 40kg

Thursday - Legs
Squat 5x5 @ 100kg
Plank 3x45s

Week 2
Monday - Push
Bench press 3x8 @ 62.5kg
Overhead press 3x10 @ 42.5kg

Thursday - Legs
Squat 5x5 @ 105kg
Plank 3x50s

About me (goal, days a week, how many weeks, equipment, current lifts): """


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
        # Type any exercise; once typed it's saved and offered here next time (no presets).
        choice = st.selectbox("Exercise", names, index=None, accept_new_options=True, key=f"wk_ex_{wid}",
                              placeholder="Type an exercise, e.g. Bench press" if not names
                              else "Pick one, or type a new one")
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
                name = (choice or "").strip()
                if not name:
                    raise wk.WorkoutError("Type the exercise.")
                ex = next((e for e in wk.exercises() if e["name"].lower() == name.lower()), None)
                if ex is None:                       # new: saved, with its type from what was filled in
                    guessed = wk.guess(name)[0]
                    kind = "cardio" if dist else "timed" if mins and not reps else \
                        guessed or ("weights" if weight else "bodyweight")
                    ex = wk.add_exercise(name, kind)
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
        kit.pills([(part, colours.get(next((n for n in names if part.startswith(n)), ""), kit.colours([0])[0]))
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


def _upload_confirm():
    """A waiting preview of an uploaded plan with Confirm / Cancel; True while one is waiting."""
    pending = st.session_state.get(UPLOAD_PENDING)
    if not pending:
        return False
    st.info(pending.summary, icon=":material/preview:")
    a, b, _ = st.columns([1, 1, 3])
    if a.button("Add to Plan", type="primary", key="wk_up_yes", icon=":material/event_available:"):
        undo.checkpoint("Uploaded a workout plan")
        r = pending.run()
        st.session_state.pop(UPLOAD_PENDING, None)
        st.toast(r.text, icon=":material/check_circle:")
        st.rerun()
    if b.button("Cancel", key="wk_up_no"):
        st.session_state.pop(UPLOAD_PENDING, None)
        st.rerun()
    return True


def _plan_cards(days):
    cols = st.columns(min(len(days), 4))
    for i, d in enumerate(days):
        with cols[i % len(cols)], st.container(border=True):
            when = f" · {wk.WEEKDAYS[d['weekday']].title()}s" if d["weekday"] is not None else ""
            st.markdown(f"**{d['name']}**{when}")
            st.markdown("\n".join(f"- {it['text']}" for it in d["items"]))


def _step(n, title, note=None):
    """A numbered step heading in the plan maker."""
    st.markdown(f"<div style='display:flex;gap:10px;align-items:center;margin:14px 0 4px'>"
                f"<span style='flex:none;width:24px;height:24px;border-radius:50%;background:#C2410C;color:#fff;"
                f"display:flex;align-items:center;justify-content:center;font-weight:700;font-size:.8rem'>{n}</span>"
                f"<b>{title}</b></div>", unsafe_allow_html=True)
    if note:
        st.caption(note)


def _upload_plan():
    """Make a plan in steps: get it written, paste it, check it, choose when, then add the sessions to the
    timetable. Only each session's name (Push, Legs...) goes in the timetable; its exercises stay in the plan."""
    with st.expander("Make a plan and put it in your week", icon=":material/upload_file:",
                     expanded=not wk.plans() or UPLOAD_PENDING in st.session_state):
        if UPLOAD_PENDING in st.session_state:
            _step(5, "Add the sessions to your timetable")
            _upload_confirm()
            return
        _step(1, "Get Claude to write your plan",
              "Copy this (the button at its top right), paste it into Claude and fill in the last line.")
        st.code(CLAUDE_PROMPT, language=None, wrap_lines=True, height=200)
        _step(2, "Paste the plan Claude wrote", "Or upload it as a .txt or .csv file.")
        f = st.file_uploader("Plan file", type=["txt", "csv", "md"], key="wk_up_file")
        text = st.text_area("Or paste the plan", key="wk_up_text", height=180, placeholder=EXAMPLE)
        if f is not None:
            text = f.getvalue().decode("utf-8", errors="replace")
        if not text.strip():
            return
        name = f.name.rsplit(".", 1)[0] if f is not None else "Workout"
        days, skipped = wk.parse_plan(text, default_name=name)
        _step(3, "Check the sessions")
        if not days:
            st.warning("No exercises found. Write them like \"Bench press 3x8 @ 60\", one per line.",
                       icon=":material/warning:")
            return
        numbered = wk.plan_weeks(days)
        if numbered:
            st.markdown(f"Found **{len(numbered)} weeks**, {len(days)} sessions in all.")
            for n, tab in zip(numbered, st.tabs([f"Week {n}" for n in numbered])):
                with tab:
                    _plan_cards([d for d in days if d["week"] == n])
        else:
            st.markdown(f"Found **{len(days)} session{'s' if len(days) != 1 else ''} a week**.")
            _plan_cards(days)
        if skipped:
            st.caption("Couldn't read: " + "; ".join(f"“{x}”" for x in skipped[:8]))
        _step(4, "Choose when they can go",
              "A day in a session's name (\"Monday - Push\") keeps it on that day; the rest are spread through "
              "the week around what's already in your timetable. Only the session names go in the timetable "
              "(\"Push\", \"Legs\"); the exercises stay in the plan, ready to start from the Log tab.")
        today = store.local_today()
        cats = list(store.load_categories()["name"])
        starts = [store.slot_time(i) for i in range(store.SLOTS)]
        ends = [store.slot_time(i) for i in range(1, store.SLOTS + 1)]
        with st.form("wk_up_form", border=False):
            a, b, c = st.columns(3)
            first = a.date_input("Starting", value=today, format=regional.input_format())
            if numbered:
                weeks = len(numbered)
                b.text_input("Weeks", value=f"{numbered[-1]} (from the plan)", disabled=True)
            else:
                weeks = b.number_input("Weeks", 1, 12, 4, help="The same sessions repeat each week.")
            minutes = c.selectbox("Each session", [30, 45, 60, 75, 90, 120], index=2,
                                  format_func=lambda m: f"{m // 60} h {m % 60} min".replace(" 0 min", "")
                                  .replace("0 h ", ""))
            a, b, c = st.columns(3)
            earliest = a.selectbox("Not before", starts, index=starts.index("07:00") if "07:00" in starts else 0,
                                   format_func=regional.time)
            latest = b.selectbox("Not after", ends, index=ends.index("21:00") if "21:00" in ends else len(ends) - 1,
                                 format_func=regional.time)
            category = c.selectbox("Category", cats, index=cats.index("Exercise") if "Exercise" in cats else 0)
            a, b, _ = st.columns([1, 1, 2])
            go = a.form_submit_button("Find times", type="primary", icon=":material/event_available:")
            save_only = b.form_submit_button("Just save the plan")
        if go:
            try:
                r = wk.schedule_plan(days, first, weeks, minutes, earliest, latest, category)
            except tools.ToolError as e:
                st.error(str(e), icon=":material/error:")
                return
            st.session_state[UPLOAD_PENDING] = r.pending
            st.rerun()
        if save_only:
            undo.checkpoint("Saved uploaded workout plans")
            for d in days:
                wk.save_plan(wk.plan_name(d), d["items"])
            st.toast(f"Saved {len(days)} session(s).", icon=":material/check_circle:")
            st.rerun()


def _plans_tab():
    _upload_plan()
    ps = wk.plans()
    if not ps:
        kit.empty("No plans yet. Upload one above, or log a workout and \"Save as plan\".", ":material/list_alt:")
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
    st.caption("Your exercises. There are no presets: any exercise you type in the Log tab (or a plan) is "
               "saved here and offered again next time.")
    if exs:
        kit.table([{"Exercise": e["name"], "Type": e["kind"], "Muscle": e["muscle"] or ""} for e in exs], height=300)
    else:
        kit.empty("None yet. Type one in the Log tab's Add sets.", ":material/fitness_center:")
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
    opts = ["(none)"] + [n for _, n in store.get_habits()]
    linked = wk.linked_habit()
    st.session_state["wk_habit"] = linked[1] if linked else "(none)"      # the saved choice (Yes on the offer, Claude)
    st.selectbox("Tick this habit when you log a workout", opts, key="wk_habit", on_change=_on_habit_pick)


def _on_habit_pick():
    pick = st.session_state["wk_habit"]
    wk.set_habit_link(None if pick == "(none)" else pick)


def _habit_offer():
    """Asks once whether workouts count towards the fitness habit (setup's "Trained"): Yes links it and ticks
    the days already trained; No is remembered. Either can be changed in the Settings tab."""
    offer = wk.habit_offer()
    if not offer:
        return
    box = st.container(border=True, horizontal=True, vertical_alignment="center", key="wk_habit_offer")
    box.markdown(f"Count your workouts towards **{offer[1]}**? Each day you log one ticks it, including the ones "
                 "you've already logged.", width="stretch")
    box.button("Yes", key="wk_offer_yes", type="primary", on_click=wk.set_habit_link, args=(offer[1],))
    box.button("No", key="wk_offer_no", on_click=wk.set_habit_link, args=(None,))


def render_page():
    st.title("Workouts")
    _habit_offer()
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


def home_status():
    """The Workouts tile's header: how many this week."""
    today = store.local_today()
    n = len(wk.workouts(store.week_start_of(today), today))
    return f"{n} this week"


def render_home():
    """Home's Workouts widget: this week as seven dots (filled on a day you trained), then the last workout."""
    from venato.ui import appearance
    kit.subhead("Workouts")
    today = store.local_today()
    start = store.week_start_of(today)
    days = {store._as_date(w["date"]) for w in wk.workouts(start, start + timedelta(days=6))}
    t = appearance.tokens()
    dots = "".join(
        f'<span class="d{" on" if start + timedelta(days=i) in days else ""}{" today" if start + timedelta(days=i) == today else ""}"'
        f' title="{store.fmt_day(start + timedelta(days=i), "%a %-d %b")}">'
        f'<i></i><b>{store.fmt_day(start + timedelta(days=i), "%a")[:1]}</b></span>' for i in range(7))
    st.html(f"""<style>
      .vn-wk-week {{ display: flex; gap: 6px; }}
      .vn-wk-week .d {{ display: flex; flex-direction: column; align-items: center; gap: 2px; flex: 1 1 0; }}
      .vn-wk-week i {{ width: 14px; height: 14px; border-radius: 50%; border: 2px solid #C2410C; box-sizing: border-box; }}
      .vn-wk-week .on i {{ background: #C2410C; }}
      .vn-wk-week b {{ font-size: 0.7rem; font-weight: 500; color: {t['muted']}; }}
      .vn-wk-week .today b {{ color: {t['ink']}; font-weight: 700; }}
    </style><div class="vn-wk-week" role="img" aria-label="{len(days)} workout days this week">{dots}</div>""")
    last = wk.workouts(today - timedelta(days=60), today)[:1]
    if not last:
        st.caption("No workouts yet. Log one on the Workouts page, or tell Claude.")
        return
    w = last[0]
    detail = wk.summary(w["id"])
    st.caption(f"Last: {store.fmt_day(store._as_date(w['date']), '%a %-d %b')}, **{kit.md(w['title'])}**"
               + (f" · {kit.md(detail[:80])}{'…' if len(detail) > 80 else ''}" if detail else ""))
