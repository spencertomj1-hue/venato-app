"""
Goals: measurable targets with a deadline ("Gym: 12 sessions by 31 Dec"), each
with a progress bar. Progress is either updated by hand (− / + / a number) or
counted automatically from a habit's ticks or timetable hours, from the day the goal is set to its deadline.

The Goals page lists the goals not past their deadline (past ones folded away under them);
Home shows the running ones as a compact list of bars.
"""

import calendar
from datetime import date, timedelta
from html import escape
from pathlib import Path

import streamlit as st

from venato import regional
from venato import store
from venato import undo
from venato.ui import kit

PAGE = "Goals"                                  # page name (also what "See all" switches to)
BY_HAND, BY_HABIT, BY_HOURS = "Update it myself", "Count a habit's ticks", "Count timetable hours"
NUMBER, MILESTONE = "Number", "Milestone"       # a target's two kinds: "50 users" or "Launch on the App Store"


def _num(x):
    return f"{store._num(x):g}" if isinstance(x, float) else str(x)


def amount(g):
    """"7 / 12 sessions"; a milestone: "3 of 5 steps", "40% (self-rated)", "done" or "to do"."""
    if g.get("milestone"):
        done, total = g.get("steps") or (0, 0)
        if g.get("self_rated"):
            return f"{round(100 * fraction(g))}% (self-rated)"
        if total:
            return f"{done} of {total} step{'s' if total != 1 else ''}"
        return "done" if fraction(g) >= 1 else "to do"
    return f"{_num(g['value'])} / {_num(g['target'])}" + (f" {g['unit']}" if g["unit"] else "")


def milestone_line(g):
    """A milestone's row: "3 of 5 steps · 60%", "Self-rated · 40%", "Done" or "Not done yet"."""
    pct = round(100 * fraction(g))
    done, total = g.get("steps") or (0, 0)
    if g.get("self_rated"):
        return f"Self-rated · {pct}%"
    if total:
        return f"{done} of {total} step{'s' if total != 1 else ''} · {pct}%"
    return "Done" if pct >= 100 else "Not done yet"


def fraction(g):
    return min(g["value"] / g["target"], 1.0) if g["target"] else 0.0


def _go_to_goals():
    st.session_state["page"] = PAGE        # the router (nav.py); set in a callback, before the page is drawn


# ---------------------------------------------------------------------------
# The deadline picker: a field that opens a small scrolling calendar
# ---------------------------------------------------------------------------

_due_component = st.components.v2.component(
    "goal_due",
    html='<div class="dp-root"></div>',
    css=(Path(__file__).parent / "components" / "due_picker_component.css").read_text(encoding="utf-8"),
    js=(Path(__file__).parent / "components" / "due_picker_component.js").read_text(encoding="utf-8"),
)


def _months_on(day, n):
    """The same day n months later (the month's last day if it's shorter)."""
    m = day.month - 1 + n
    y, m = day.year + m // 12, m % 12 + 1
    return date(y, m, min(day.day, calendar.monthrange(y, m)[1]))


def handy_deadlines(today):
    """The deadlines marked on the calendar, soonest first: [(date, label)]."""
    marks = {}
    for day, text in [(today + timedelta(days=14), "2 weeks from now"),
                      (store.end_of_period("monthly", today.replace(day=1)), "End of the month"),
                      (_months_on(today, 1), "A month from now"), (date(today.year, 12, 31), "End of the year"),
                      (_months_on(today, 12), "A year from now")]:
        marks[day] = f"{marks[day]} · {text}" if day in marks else text      # two on one day: one marker
    return sorted(marks.items())


def default_due(today):
    """A new goal's deadline until you pick one: the end of the month (a month from now in its last week)."""
    end = store.end_of_period("monthly", today.replace(day=1))
    return end if (end - today).days >= 7 else _months_on(today, 1)


def due_picker(key, value, label="Deadline"):
    """The deadline field for the form with this key; returns the picked date (kept in session state)."""
    today = store.local_today()
    skey = f"{key}_due"
    st.session_state.setdefault(skey, value)

    def picked():
        day = (st.session_state[f"{key}_duecal"]["pick"] or {}).get("date")
        if day:
            st.session_state[skey] = date.fromisoformat(day)

    due = st.session_state[skey]
    months = max(26, (due.year - today.year) * 12 + due.month - today.month + 3)
    _due_component(data={"value": due.isoformat(), "today": today.isoformat(), "months": months, "label": label,
                         "weekStart": regional.week_start(), "weekdays": regional.weekday_names(),
                         "marks": [{"date": d.isoformat(), "label": text} for d, text in handy_deadlines(today)],
                         "shortcuts": [{"date": date(today.year, 12, 31).isoformat(), "label": "End of the year"},
                                       {"date": _months_on(today, 12).isoformat(), "label": "In a year"}]},
                   key=f"{key}_duecal", on_pick_change=picked)
    return due


# ---------------------------------------------------------------------------
# The form shared by "New goal" and "Edit"
# ---------------------------------------------------------------------------

def _goal_form(key, goal=None, life_goal_id=None):
    """Title, target, unit, deadline, the long-term goal it's under and how progress is tracked. Returns the
    values, or None if a habit choice is missing."""
    habits = dict(store.get_habits())                       # id -> name
    cats = store.load_categories()
    categories = dict(zip(cats["id"], cats["name"]))        # id -> name
    is_milestone = bool(goal and goal.get("milestone"))
    kind = st.segmented_control("Kind", [NUMBER, MILESTONE], default=MILESTONE if is_milestone else NUMBER,
                                key=f"{key}_kind", width="stretch",
                                help="Number: something you can count (50 users, 40 gym sessions). "
                                     "Milestone: something you get done (launch the app); its to-dos are its steps.")
    if kind == MILESTONE:
        return _milestone_form(key, goal, life_goal_id)
    title = st.text_input("Target", value=goal["title"] if goal else "", key=f"{key}_title",
                          placeholder="e.g. Gym")
    a, b = st.columns(2)
    target = a.number_input("Aim for", min_value=0.5, step=1.0,
                            value=float(goal["target"]) if goal and not is_milestone else 10.0, format="%g",
                            key=f"{key}_target")
    unit = b.text_input("Unit (optional)", value=(goal["unit"] or "") if goal else "", key=f"{key}_unit",
                        placeholder="sessions, km, books…")
    due = due_picker(key, date.fromisoformat(goal["due"]) if goal else default_due(store.local_today()))
    mode = 2 if goal and goal.get("kind") == "hours" else 1 if goal and goal["habit_id"] is not None else 0
    how = st.radio("Progress", [BY_HAND, BY_HABIT, BY_HOURS], index=mode, key=f"{key}_how", horizontal=True,
                   help="Count a habit's ticks: every day you tick that habit before the deadline adds 1. "
                        "Count timetable hours: the hours in your timetable's Actual track in a category "
                        "(and, if you like, only one activity) add up by themselves.")
    values = {"title": title.strip(), "target": target, "unit": unit.strip() or None, "habit_id": None,
              "category_id": None, "label": None, "due": due, "milestone": False,
              "life_goal_id": _life_goal_picker(key, goal["life_goal_id"] if goal else life_goal_id),
              "effort": kit.effort_picker(key, goal.get("effort") if goal else None)}
    if how == BY_HABIT:
        if not habits:
            st.caption("You have no habits yet. Add one on the Daily Log page, or update this goal yourself.")
            return None
        ids = list(habits)
        values["habit_id"] = st.selectbox("Habit", ids, format_func=habits.get, key=f"{key}_habit",
                                          index=ids.index(goal["habit_id"]) if mode == 1 and goal["habit_id"] in ids else 0)
    elif how == BY_HOURS:
        if not categories:
            from venato.ui import timetable_tools
            timetable_tools.no_categories(f"{key}_addcat", "Counting timetable hours needs a category to count. "
                                          "Add one first, or track this goal by hand.")
            return None
        ids = list(categories)
        c, d = st.columns(2)
        values["category_id"] = c.selectbox("Category", ids, format_func=categories.get, key=f"{key}_cat",
                                            index=ids.index(goal["category_id"]) if mode == 2 and goal["category_id"] in ids else 0)
        values["label"] = d.text_input("Only this activity (optional)", value=(goal.get("label") or "") if mode == 2 else "",
                                       key=f"{key}_label", placeholder="e.g. Guitar").strip() or None
        values["unit"] = values["unit"] or "h"
    values["start"], values["earlier"] = _earlier(key, values, goal)
    return values


def _milestone_form(key, goal, life_goal_id):
    """A milestone's form: title, deadline, the goal it's under and, if you like, "How far, honestly?"
    (a self-rating that replaces counting its to-dos). No amount, unit or source."""
    title = st.text_input("Target", value=goal["title"] if goal else "", key=f"{key}_title",
                          placeholder="e.g. Launch on the App Store")
    due = due_picker(key, date.fromisoformat(goal["due"]) if goal else default_due(store.local_today()))
    values = {"title": title.strip(), "milestone": True, "due": due,
              "life_goal_id": _life_goal_picker(key, goal["life_goal_id"] if goal else life_goal_id),
              "effort": kit.effort_picker(key, goal.get("effort") if goal else None), "start": None, "earlier": 0.0}
    rating = goal.get("self_rating") if goal else None
    rate = st.toggle("Rate it myself", value=rating is not None, key=f"{key}_rate",
                     help="For fuzzy ones (\"get good at Swift\"): your own guess replaces counting its to-dos.")
    values["self_rating"] = None
    if rate:
        pct = st.slider("How far, honestly?", 0, 100, value=round(100 * (rating or 0)), step=5, format="%d%%",
                        key=f"{key}_rating")
        values["self_rating"] = pct / 100
    else:
        st.caption("Its to-dos are its steps: it fills up as you tick them. With none, tick it when it's done.")
    return values


def _life_goal_picker(key, current):
    """Which long-term goal a target is under (or none). Hidden while there are no goals."""
    lives = store.life_goals(include_past=True)
    if not lives:
        return current
    ids = [None] + [g["id"] for g in lives]
    names = {g["id"]: g["title"] for g in lives}
    return st.selectbox("Under goal", ids, index=ids.index(current) if current in ids else 0, key=f"{key}_life",
                        format_func=lambda i: names.get(i, "No goal"))


def _earlier(key, values, goal=None):
    """Folded away under the form: progress made before today. "Count from" (a day you pick)
    moves the goal's start back (a habit's ticks or timetable hours from then count by themselves);
    a goal kept by hand also takes how much was done in that time. Returns (new start or None, amount)."""
    today = store.local_today()
    since = date.fromisoformat(goal["period_start"]) if goal else today
    picked = st.session_state.get(f"{key}_since")
    with st.expander("Already made progress?", icon=":material/history:",
                     expanded=picked is not None and picked != since):          # (stays open once changed)
        start = st.date_input("Count from", value=since, max_value=max(since, today), key=f"{key}_since",
                              format=regional.input_format(),
                              help="Move the goal's start back so what you did since then counts")
        if not start or start == since:
            return None, 0.0
        auto = store.counted_between(start, today, values["habit_id"], values["category_id"], values["label"])
        if auto is not None:
            what = f"{_num(auto)} {values['unit'] or ''}".strip()
            st.caption(f"Since {regional.short_date(start, today)}: {what} so far, counted automatically.")
            return start, 0.0
        done = st.number_input("Done in that time", min_value=0.0, step=1.0, value=0.0, format="%g",
                               key=f"{key}_ago_done")
        return start, done


def _new_goal(key="new_goal", life_goal_id=None):
    """"Add target": a measurable target with a deadline (under `life_goal_id`, which the form can change)."""
    with st.popover("Add target", icon=":material/add:", width="stretch"):
        values = _goal_form(key, life_goal_id=life_goal_id)
        if st.button("Add target", key=f"{key}_add", type="primary", disabled=not values or not values["title"]):
            if values["milestone"]:
                today = store.local_today()
                g = store.add_goal(values["title"], None, today, None, due=max(values["due"], today),
                                   life_goal_id=values["life_goal_id"], milestone=True, effort=values["effort"])
                if values["self_rating"] is not None:
                    store.update_goal(g["id"], self_rating=values["self_rating"])
            else:
                g = store.add_goal(values["title"], None, values["start"] or store.local_today(), values["target"],
                                   values["unit"], values["habit_id"], category_id=values["category_id"],
                                   label=values["label"], due=max(values["due"], values["start"] or values["due"]),
                                   life_goal_id=values["life_goal_id"], effort=values["effort"])
            if values["earlier"]:
                store.set_goal_progress(g["id"], values["earlier"])
            for k in [k for k in st.session_state if k.startswith(f"{key}_")]:
                del st.session_state[k]                      # an empty form next time
            st.rerun()


def _move(ids, goal_id, step):
    """Move a goal up or down its list: the order is its priority when goals compete for time."""
    i = ids.index(goal_id)
    j = i + step
    if 0 <= j < len(ids):
        ids = list(ids)
        ids[i], ids[j] = ids[j], ids[i]
        store.reorder_goals(ids)


def _edit_goal(g, ids=None):
    with st.popover("", icon=":material/more_horiz:", help="Edit, move or delete"):
        key = f"edit_{g['id']}"
        if ids and len(ids) > 1:
            up, down = st.columns(2)
            up.button("Move up", icon=":material/arrow_upward:", key=f"{key}_up", width="stretch",
                      disabled=ids[0] == g["id"], on_click=_move, args=(ids, g["id"], -1),
                      help="Higher goals get free time first when goals compete for it")
            down.button("Move down", icon=":material/arrow_downward:", key=f"{key}_down", width="stretch",
                        disabled=ids[-1] == g["id"], on_click=_move, args=(ids, g["id"], 1))
        values = _goal_form(key, g)
        number = bool(values) and not values["milestone"]
        if g["kind"] == "count" and number and not g["milestone"]:
            progress = st.number_input("Progress so far", min_value=0.0, step=1.0, value=float(g["progress"]), format="%g",
                                       key=f"{key}_progress")
        save, delete = st.columns(2)
        if save.button("Save", key=f"{key}_save", type="primary", width="stretch",
                       disabled=not values or not values["title"]):
            start, earlier = values.pop("start"), values.pop("earlier")
            first = start or date.fromisoformat(g["period_start"])
            values["due"] = max(values["due"], first)                     # (never before the day it counts from)
            store.update_goal(g["id"], **values, **({"start": start} if start else {}))
            for k in ("due", "since", "ago_done"):
                st.session_state.pop(f"{key}_{k}", None)
            if g["kind"] == "count" and number and not g["milestone"] \
                    and values["habit_id"] is None and values["category_id"] is None:
                store.set_goal_progress(g["id"], progress + earlier)
            st.rerun()
        if delete.button("Delete", key=f"{key}_delete", icon=":material/delete:", width="stretch"):
            undo.checkpoint(f"Deleted the target '{g['title']}'")
            store.delete_goal(g["id"])
            st.rerun()


# ---------------------------------------------------------------------------
# Goals page
# ---------------------------------------------------------------------------

def _goal_row(g, ctx=None, neighbours=None):
    """One target as a compact row: title, state badge and time left; a progress bar with the "should be here
    by today" tick; its %; − / + (kept by hand) and ⋯. The pace chart and detail lines fold away under it."""
    from venato import pace
    from venato.ui import goal_chart, goal_time
    p = pace.goal_pace(g, ctx) if ctx is not None else None
    today = ctx.today if ctx is not None else store.local_today()
    with st.container(border=True, key=f"goal_card_{g['id']}"):
        text, bar, pct, minus, plus, more = st.columns([3.2, 3, 0.8, 0.6, 0.6, 0.9], vertical_alignment="center")
        when, left = due_parts(g)
        badge = f"{goal_time.badge(p['state'])} " if p and p["state"] != "upcoming" else ""
        # The deadline stays on the title's line (non-breaking spaces keep "by 31/12" in one piece).
        text.markdown(f"**{goal_time.md(g['title'])}**\u00a0:gray[{when.replace(' ', chr(160))}]\u00a0"
                      f"{kit.effort_html(g.get('effort'))}  \n{badge}:gray[{left}]", unsafe_allow_html=True)
        unit = f" {g['unit']}" if g["unit"] else ""
        should = pace.expected(g, today) if g["target"] else 0
        if g["milestone"]:
            line = milestone_line(g)
            if 0 < should and fraction(g) < 1:
                line += f" · pace says {round(100 * should)}%"
        else:
            line = f"{_num(g['value'])} of {_num(g['target'])}{unit}"
            if 0 < should and fraction(g) < 1:
                line += f" · pace says {_num(round(should, 1))}"
        with bar:
            st.html(goal_bar_css() + goal_bar(g, today, line))
        pct.markdown(f"#### {round(100 * fraction(g))}%")
        if g["milestone"]:
            minus.empty()
            _milestone_tick(g, plus)
        elif g["kind"] != "count":
            minus.empty()
            plus.empty()
        else:
            minus.button("", icon=":material/remove:", key=f"minus_{g['id']}", help=f"Take 1 off {g['title']}",
                         on_click=store.add_goal_progress, args=(g["id"], -1), disabled=g["value"] <= 0)
            plus.button("", icon=":material/add:", key=f"plus_{g['id']}", help=f"Add 1 to {g['title']}",
                        on_click=store.add_goal_progress, args=(g["id"], 1))
        with more:
            _edit_goal(g, neighbours)
        lines = list(p.get("details") or []) if p else []
        week = goal_chart.week_line(p) if p else ""
        if week:
            lines.insert(0, week)
        svg = goal_chart.chart(p, ctx) if p else ""
        source = ""
        if g["habit"]:
            source = f":material/sync: Counted from the habit **{escape(g['habit'])}**"
        elif g["category"]:
            what = f"{g['label']} ({g['category']})" if g.get("label") else g["category"]
            source = (f":material/schedule: Counted from your timetable's Actual hours of **{escape(what)}**, "
                      "on days you've confirmed")
        _target_todos(g)
        with st.expander("Chart, to-dos and details", icon=":material/show_chart:"):
            if svg:
                st.html(svg)
            if lines:
                st.caption("  \n".join(goal_time.md(x) for x in lines))
            if source:
                st.caption(source)
            _new_target_todo(g)


def _milestone_tick(g, where):
    """A milestone's tick box: ticks it done (or undone) when it has no to-dos and no self-rating; otherwise it
    shows where it stands and ticks itself (its to-dos, or the rating, decide)."""
    done = fraction(g) >= 1
    steps = (g.get("steps") or (0, 0))[1]
    by_hand = not steps and not g.get("self_rated")
    where.checkbox("Done", value=done, key=f"milestone_{g['id']}_{done}", label_visibility="collapsed",
                   disabled=not by_hand, on_change=store.set_goal_progress, args=(g["id"], 0 if done else 1),
                   help=f"Tick {g['title']} when it's done" if by_hand else
                   "Ticks itself when its to-dos are done" if steps else "Self-rated: change it from ⋯")


def _plus_offer_key(target_id):
    return f"plus_offer_{target_id}"


def _tick_target_todo(todo_id, target):
    """Tick a target's to-do; on a target kept by hand, offer to add 1 to it too."""
    store.set_todo_done(todo_id, True)
    if target["kind"] == "count" and not target["milestone"]:
        st.session_state[_plus_offer_key(target["id"])] = True


def _accept_plus(target_id):
    store.add_goal_progress(target_id, 1)
    st.session_state.pop(_plus_offer_key(target_id), None)


def _target_todos(g):
    """A target's open to-dos, to tick right on its row (done ones counted), and the "+1?" offer after a tick."""
    todos = store.target_todos(g["id"])
    open_ = [t for t in todos if not t["done"]]
    today = store.local_today()
    for t in open_:
        when = f" :gray[· due {regional.short_date(t['due'], today)}]" if t.get("due") else ""
        st.checkbox(f"{kit.md(t['title'])}{when} {kit.effort_label(t.get('effort'))}", value=False,
                    key=f"target_todo_{t['id']}", help=f"Effort {store.effort(t)} of 10",
                    on_change=_tick_target_todo, args=(t["id"], g))
    if st.session_state.get(_plus_offer_key(g["id"])):
        with st.container(horizontal=True, gap="small", vertical_alignment="center"):
            st.caption(f"Ticked. Add 1 to **{kit.md(g['title'])}** too?")
            st.button("+1", key=f"plus_offer_yes_{g['id']}", on_click=_accept_plus, args=(g["id"],))
            st.button("No", key=f"plus_offer_no_{g['id']}", type="tertiary",
                      on_click=st.session_state.pop, args=(_plus_offer_key(g["id"]), None))
    done = len(todos) - len(open_)
    if done:
        st.caption(f"{done} to-do{'s' if done != 1 else ''} done")


def _new_target_todo(g):
    """A line to add a to-do to this target (it goes in the target's own to-do category)."""
    key = f"target_{g['id']}_newtodo"
    with st.container(horizontal=True, vertical_alignment="bottom"):
        title = st.text_input("New to-do", key=key, placeholder="Add a to-do for this target",
                              label_visibility="collapsed", width="stretch")
        effort = kit.effort_picker(key, exact=False)
        if st.button("", icon=":material/add:", key=f"{key}_add", help="Add this to-do to the target",
                     disabled=not (title or "").strip()):
            store.add_detailed_todo(title.strip(), group_id=store.ensure_target_group(g["id"]), effort=effort)
            for k in (key, f"{key}_effort"):
                st.session_state.pop(k, None)
            st.rerun()


def due_parts(g, today=None):
    """(the deadline, how long is left): ("by 31/12", "44 days left"), ("by 31/10", "ended"),
    ("by 31/12", "starts 01/12")."""
    today = today or store.local_today()
    due, start = date.fromisoformat(g["due"]), date.fromisoformat(g["period_start"])
    left = (due - today).days
    when = store.goal_title_due(due, today)
    if start > today:
        return when, f"starts {regional.short_date(start, today)}"
    if left < 0:
        return when, "ended"
    return when, "due today" if left == 0 else "1 day left" if left == 1 else f"{left} days left"


def _section(today, ctx):
    """The targets under no long-term goal (deadline plans among them), and every past target folded away."""
    goals = store.unparented_targets(today)
    done = sum(fraction(g) >= 1 for g in goals)
    with st.container(border=True):
        heading = "Targets" if not store.life_goals(include_past=True) else "Targets not under a goal"
        st.subheader(f"{heading} :gray[{done}/{len(goals)}]", anchor=False)
        ids = [g["id"] for g in goals]
        for g in goals:
            _goal_row(g, ctx, ids)
        if not goals:
            st.caption("None. Measurable targets with a deadline (\"Gym 40 sessions by 31/03\") go here or under a goal.")
        _new_goal()
    from venato import pace
    past = pace.goals_past(today)
    if past:
        with st.expander(f"Past targets ({sum(fraction(g) >= 1 for g in past)}/{len(past)} done)"):
            for g in past:
                _goal_row(g)


def render_page():
    st.header("Goals", anchor=False)
    st.caption("Your plans for the next 3, 6 or 12 months. Under each: targets (measurable, by a date) and to-dos.")
    today = store.local_today()
    from venato import pace
    from venato.ui import goal_time
    from venato.ui import goal_chart
    ctx = pace.Ctx()
    goal_time.offers(ctx)                               # "X can't be finished in time", above everything
    st.html(goal_chart.legend())                        # once, for every target's pace chart
    from venato.ui import life_goals
    life_goals.render_section(ctx, today)
    _section(today, ctx)
    from venato.ui import deadlines
    deadlines.render_section()


# ---------------------------------------------------------------------------
# Home: this month's and this year's goals as progress bars
# ---------------------------------------------------------------------------

def _accent():
    from venato.ui import appearance
    return appearance.accent()                 # the theme's accent in light or dark (#C62828 / #FF6B6B)


def _fill(g):
    return f'<i style="width:{100 * fraction(g):.1f}%"></i>'


# The progress bar used on both pages, in the app's accent colour (st.progress has its own colour).
BAR_CSS = """<style>
  .hg-bar { height: 7px; border-radius: 999px; background: rgba(128, 128, 128, 0.18); overflow: hidden; }
  .hg-bar i { display: block; height: 100%; border-radius: 999px; background: ACCENT; transition: width 0.4s ease; }
</style>"""


def _marker(g, today):
    """The "should be here by today" tick on a goal's bar (an even pace from the day it was set to its deadline)."""
    from venato import pace
    should = pace.expected(g, today)
    if fraction(g) >= 1 or should <= 0:
        return ""
    pct = 100 * min(should / g["target"], 1.0)
    text = (f"Should be at {round(pct)}% by today" if g.get("milestone")
            else f"Should be at {_num(round(should, 1))} of {_num(g['target'])} by today")
    return f'<span class="hg-mark" role="img" aria-label="{escape(text)}" title="{escape(text)}" style="left:{pct:.1f}%"></span>'


STATUS_ICON = {"done": "✓", "on_track": "✓", "behind": "⚠", "slipping": "⚠", "unreachable": "✕", "ended": "■",
               "upcoming": "○"}


def pace_detail(p):
    """How far off today's pace, in words ("3.5 h under today's pace"), or "" when there's nothing to add."""
    from venato import pace
    g, state = p["goal"], p["state"]
    if state == "behind" and p["expected"] - p["value"] >= 0.05:
        return f"{pace.amount(g, p['expected'] - p['value'])} under today's pace"
    if state == "behind" and p.get("late"):
        return f"{p['late']} days late at this rate"
    if state == "slipping":
        return "done is trailing the Plan this week"
    if state == "unreachable":
        return "not enough time left"
    return ""


def status_line(p):
    """One short line: the state (icon + word, never colour alone) and how far off today's pace."""
    from venato import pace
    detail = pace_detail(p)
    return f"{STATUS_ICON[p['state']]} {pace.STATES[p['state']]}" + (f": {detail}" if detail else "")


def goal_bar(g, today, line=""):
    """A goal's progress bar with the "should be here by today" tick, and a line under it."""
    return (f'<div class="hg-track"><div class="hg-bar">{_fill(g)}</div>{_marker(g, today)}</div>'
            + (f'<div class="hg-line">{escape(line)}</div>' if line else ""))


HOME_LIMIT = 3          # goals Home's tile shows before "and N more"
_BEHIND_FIRST = {"unreachable": 0, "behind": 0, "slipping": 1}     # the rest keep their list order after these


def home_goals(ctx=None):
    """The goals running now as Home lists them: [(goal, pace)], the ones behind (or out of reach, or slipping)
    first, the rest in their usual order."""
    from venato import pace
    ctx = ctx or pace.Ctx()
    rows = [(p["goal"], p) for p in pace.pace_all(ctx)]
    return sorted(rows, key=lambda r: _BEHIND_FIRST.get(r[1]["state"], 2))


GOALS_SHOWN = 4         # long-term goals Home's tile shows at any size; the ones behind are kept when trimming

# Home's Goals tile with long-term goals, per tile size: what each goal's row shows (_home_life_goals).
#   small  name, bar with the pace tick, %                 wide   + its next target on the right
#   tall   a block each: name and %, bar, next target and time left, then the next move
#   large  + every target as a chip with its own bar       column tall + its open to-dos, to tick here
_SIZE_TODOS = {"column": 2}
_NEXT_MOVE = ("tall", "large", "column")


def _pick(rows, n):
    """The goals to show: all of them when they fit, else the behind ones first (furthest behind first),
    then the rest, kept in their list order."""
    if len(rows) <= n:
        return rows
    keep = sorted(range(len(rows)), key=lambda i: (not rows[i]["behind"], rows[i]["fraction"] - rows[i]["expected"]))[:n]
    return [rows[i] for i in sorted(keep)]


def _say(r, today):
    """A goal's row in words, for screen readers and the hover title."""
    pct, exp = round(100 * r["fraction"]), round(100 * r["expected"])
    state = f"behind: {exp}% by now" if r["behind"] else "on track"
    return f"{r['goal']['title']}: {pct}% done, {state}, {store.time_left(r['goal'], today)}"


def _next_text(r, today):
    n = r["next"]
    if not n:
        return ""
    what = "" if n.get("milestone") and not (n.get("steps") or (0, 0))[1] else f" · {amount(n)}"   # (a bare tick)
    return f"{n['title']}{what} {store.goal_title_due(n['due'], today)}"


def _gw_bar(r, today, height=8):
    c = r["colour"]
    return (f'<div class="gw-track" role="img" aria-label="{escape(_say(r, today))}" '
            f'style="height:{height}px;background:{c}33"><i style="width:{100 * r["fraction"]:.1f}%;background:{c}"></i>'
            f'<span class="gw-tick" style="left:{100 * r["expected"]:.1f}%"></span></div>')


def _gw_pct(r):
    return f'<span class="gw-pct{" gw-behind" if r["behind"] else ""}">{round(100 * r["fraction"])}%</span>'


def _gw_name(r):
    return (f'<span class="gw-name"><span class="gw-dot" style="background:{r["colour"]}"></span>'
            f'<span>{escape(r["goal"]["title"])}</span></span>')


def _gw_row(r, today, size):
    """One goal on the tile, as `size` draws it."""
    nxt = _next_text(r, today)
    title = escape(_say(r, today))
    if size in ("small", "wide"):
        side = f'<span class="gw-next">{"Next: " + escape(nxt) if nxt else ""}</span>' if size == "wide" else ""
        return f'<div class="gw-line gw-{size}" title="{title}">{_gw_name(r)}{_gw_bar(r, today)}{_gw_pct(r)}{side}</div>'
    sub = (f'<div class="gw-sub"><span class="gw-next">{"Next: " + escape(nxt) if nxt else "No open target"}</span>'
           f'<span>{escape(store.time_left(r["goal"], today))}</span></div>')
    if size == "large":
        chips = "".join(
            f'<span class="gw-chip">{escape(t["title"])}<span class="gw-mini" style="background:{r["colour"]}33">'
            f'<i style="width:{100 * fraction(t):.0f}%;background:{r["colour"]}"></i></span>'
            f'<span class="gw-muted">{escape(amount(t))}</span></span>' for t in r["targets"])
        state = (f'<span class="gw-behind">behind {round(100 * (r["expected"] - r["fraction"]))}%</span>'
                 if r["behind"] else "on track")
        return (f'<div class="gw-big" title="{title}"><div>{_gw_name(r)}<div class="gw-sub gw-indent">'
                f'{escape(store.time_left(r["goal"], today))} · {state}</div></div>'
                f'<div><div class="gw-barline">{_gw_bar(r, today)}{_gw_pct(r)}</div>'
                f'<div class="gw-chips">{chips}</div></div></div>')
    return f'<div class="gw-block" title="{title}"><div class="gw-head">{_gw_name(r)}{_gw_pct(r)}</div>{_gw_bar(r, today)}{sub}</div>'


def _next_move(rows, today):
    """The goal furthest behind and the one thing to do next for it, or None when none is behind."""
    behind = [r for r in rows if r["behind"]]
    if not behind:
        return None
    r = min(behind, key=lambda r: r["fraction"] - r["expected"])
    todo = (r["todos"] or store.life_goal_todos(r["goal"]["id"], open_only=True)[:1] or [None])[0]
    if r["next"]:
        step = f"{r['next']['title']} ({amount(r['next'])})"
    elif todo:
        step = todo["title"]
    else:
        step = "give it a target or a to-do"
    return r, f"{r['goal']['title']} is furthest behind. Next: {step}"


def _gw_css():
    from venato.ui import appearance
    bad = appearance.warn_colours()[1]
    return f"""<style>
      .gw-rows {{ display: flex; flex-direction: column; gap: 12px; }}
      .gw-track {{ position: relative; border-radius: 999px; }}
      .gw-track > i {{ position: absolute; left: 0; top: 0; bottom: 0; border-radius: 999px; }}
      .gw-tick {{ position: absolute; top: -4px; bottom: -4px; width: 2px; margin-left: -1px; border-radius: 1px;
                  background: currentColor; opacity: 0.85; }}
      .gw-name {{ display: flex; align-items: center; gap: 8px; min-width: 0; font-weight: 600; font-size: 0.9rem; }}
      .gw-name > span:last-child {{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
      .gw-dot {{ width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }}
      .gw-pct {{ font-weight: 600; font-size: 0.85rem; text-align: right; font-variant-numeric: tabular-nums; }}
      .gw-behind {{ color: {bad}; font-weight: 600; }}
      .gw-next, .gw-muted {{ opacity: 0.75; }}
      .gw-next {{ font-size: 0.78rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }}
      .gw-line {{ display: grid; align-items: center; gap: 12px; }}
      .gw-small {{ grid-template-columns: minmax(0, 40%) minmax(0, 1fr) 3em; }}
      .gw-wide {{ grid-template-columns: minmax(0, 24%) minmax(0, 1fr) 3em minmax(0, 36%); }}
      .gw-block {{ display: flex; flex-direction: column; gap: 7px; padding-bottom: 10px;
                   border-bottom: 1px solid rgba(128, 128, 128, 0.18); }}
      .gw-head, .gw-sub {{ display: flex; align-items: center; gap: 8px; }}
      .gw-head .gw-pct {{ margin-left: auto; }}
      .gw-sub {{ font-size: 0.78rem; }}
      .gw-sub > span:last-child {{ margin-left: auto; white-space: nowrap; opacity: 0.75; }}
      .gw-indent {{ padding-left: 18px; margin-top: 4px; display: block; opacity: 0.85; }}
      .gw-big {{ display: grid; grid-template-columns: minmax(0, 32%) minmax(0, 1fr); gap: 16px; padding-bottom: 10px;
                 border-bottom: 1px solid rgba(128, 128, 128, 0.18); }}
      .gw-barline {{ display: grid; grid-template-columns: minmax(0, 1fr) 3em; gap: 12px; align-items: center; }}
      .gw-chips {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }}
      .gw-chip {{ display: inline-flex; align-items: center; gap: 6px; font-size: 0.75rem; padding: 2px 8px;
                  border-radius: 8px; background: rgba(128, 128, 128, 0.1); }}
      .gw-mini {{ position: relative; width: 36px; height: 4px; border-radius: 2px; display: inline-block; }}
      .gw-mini > i {{ position: absolute; left: 0; top: 0; bottom: 0; border-radius: 2px; }}
      .gw-move {{ display: flex; gap: 8px; align-items: baseline; font-size: 0.82rem; padding: 8px 12px;
                  border-radius: 10px; background: rgba(128, 128, 128, 0.1); margin-top: 4px; }}
      .gw-move .gw-dot {{ width: 8px; height: 8px; }}
      .gw-more {{ font-size: 0.8rem; opacity: 0.75; }}
    </style>"""


def _home_life_goals(today, size="wide"):
    """Home's Goals tile with long-term goals, drawn for the tile's size (see _SIZE_TODOS / _NEXT_MOVE above):
    each goal in its colour with a bar and the "should be here by today" tick; at Column, its open to-dos
    to tick straight from Home."""
    from venato.ui import life_goals
    rows = life_goals.home_rows(today, todos=_SIZE_TODOS.get(size, 0))
    shown = _pick(rows, GOALS_SHOWN)
    more = f'<div class="gw-more">+{len(rows) - len(shown)} more</div>' if len(rows) > len(shown) else ""
    move = _next_move(rows, today) if size in _NEXT_MOVE else None
    move_html = (f'<div class="gw-move"><span class="gw-dot" style="background:{move[0]["colour"]}"></span>'
                 f'<span><b>Next move:</b> {escape(move[1])}</span></div>') if move else ""
    if size != "column":
        st.html(_gw_css() + f'<div class="gw-rows">{"".join(_gw_row(r, today, size) for r in shown)}{more}{move_html}</div>')
        return
    st.html(_gw_css())
    for r in shown:
        st.html(_gw_row(r, today, size))
        for t in r["todos"]:
            st.checkbox(kit.md(t["title"]), value=False, key=f"home_goal_todo_{t['id']}",
                        on_change=store.set_todo_done, args=(t["id"], True))
    if more or move_html:
        st.html(f'<div class="gw-rows">{more}{move_html}</div>')


def render_home(size="wide"):
    """Home's Goals tile: the long-term goals when there are any (_home_life_goals, drawn for `size`); otherwise the top three
    targets (behind ones first), each its name and a thin bar with the "should be here by today" tick on one
    line, then "and N more". Everything else is on the Goals page."""
    today = store.local_today()
    head = st.container(horizontal=True, vertical_alignment="center")
    kit.subhead("Goals", head, width="stretch")
    head.button("See all", key="home_goals_all", type="tertiary", on_click=_go_to_goals)
    if store.life_goals(today):
        _home_life_goals(today, size)
        return
    rows = home_goals()
    if not rows:
        st.caption("No goals running. Set one on the Goals page.")
        return
    lines = []
    for g, p in rows[:HOME_LIMIT]:
        say = f"{g['title']}: {amount(g)} {store.goal_title_due(g['due'], today)}, {status_line(p)}"
        lines.append(f'<div class="hg-row" title="{escape(say)}"><span class="hg-name">{escape(g["title"])}</span>'
                     f'<div class="hg-track" role="img" aria-label="{escape(say)}"><div class="hg-bar">{_fill(g)}</div>'
                     f'{_marker(g, today)}</div></div>')
    st.html(goal_bar_css() + """<style>
      .hg-rows { display: flex; flex-direction: column; gap: 8px; }
      .hg-row { display: grid; grid-template-columns: minmax(0, 38%) minmax(0, 1fr); align-items: center; gap: 12px; }
      .hg-name { font-size: 0.9rem; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .hg-row .hg-bar { height: 5px; }
      .hg-row .hg-mark { top: -3px; height: 11px; }
      .hg-more { font-size: 0.875rem; opacity: 0.85; }
    </style>""" + f'<div class="hg-rows">{"".join(lines)}'
            + (f'<div class="hg-more">and {len(rows) - HOME_LIMIT} more</div>' if len(rows) > HOME_LIMIT else "")
            + "</div>")


def goal_bar_css():
    """The styles goal_bar needs (the bar in the theme's accent)."""
    return ("""<style>
      .hg-track { position: relative; }
      .hg-mark { position: absolute; top: -4px; width: 2px; height: 15px; margin-left: -1px; border-radius: 1px;
                 background: currentColor; opacity: 0.85; }
      .hg-title { font-size: 0.9rem; font-weight: 600; margin-bottom: 4px; }
      .hg-line { font-size: 0.8rem; opacity: 0.8; margin-top: 3px; font-variant-numeric: tabular-nums; }
    </style>""" + BAR_CSS.replace("ACCENT", _accent()))
