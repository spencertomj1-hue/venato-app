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

PAGE = "Goals"                                  # sidebar label (also what "See all" switches to)
BY_HAND, BY_HABIT, BY_HOURS = "Update it myself", "Count a habit's ticks", "Count timetable hours"


def _num(x):
    return f"{store._num(x):g}" if isinstance(x, float) else str(x)


def amount(g):
    """"7 / 12 sessions"."""
    return f"{_num(g['value'])} / {_num(g['target'])}" + (f" {g['unit']}" if g["unit"] else "")


def fraction(g):
    return min(g["value"] / g["target"], 1.0) if g["target"] else 0.0


def _go_to_goals():
    st.session_state["page"] = PAGE        # the sidebar radio's key; button callbacks run before it's drawn


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

def _goal_form(key, goal=None):
    """Title, target, unit, deadline and how progress is tracked. Returns the values, or None if a habit choice is missing."""
    habits = dict(store.get_habits())                       # id -> name
    cats = store.load_categories()
    categories = dict(zip(cats["id"], cats["name"]))        # id -> name
    title = st.text_input("Goal", value=goal["title"] if goal else "", key=f"{key}_title",
                          placeholder="e.g. Gym")
    a, b = st.columns(2)
    target = a.number_input("Target", min_value=0.5, step=1.0, value=float(goal["target"]) if goal else 10.0, format="%g",
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
              "category_id": None, "label": None, "due": due}
    if how == BY_HABIT:
        if not habits:
            st.caption("You have no habits yet. Add one on the Daily Log page, or update this goal yourself.")
            return None
        ids = list(habits)
        values["habit_id"] = st.selectbox("Habit", ids, format_func=habits.get, key=f"{key}_habit",
                                          index=ids.index(goal["habit_id"]) if mode == 1 and goal["habit_id"] in ids else 0)
    elif how == BY_HOURS:
        ids = list(categories)
        c, d = st.columns(2)
        values["category_id"] = c.selectbox("Category", ids, format_func=categories.get, key=f"{key}_cat",
                                            index=ids.index(goal["category_id"]) if mode == 2 and goal["category_id"] in ids else 0)
        values["label"] = d.text_input("Only this activity (optional)", value=(goal.get("label") or "") if mode == 2 else "",
                                       key=f"{key}_label", placeholder="e.g. Guitar").strip() or None
        values["unit"] = values["unit"] or "h"
    values["start"], values["earlier"] = _earlier(key, values, goal)
    return values


EARLIER_UNITS = {"weeks": 7, "months": None, "days": 1}


def _earlier(key, values, goal=None):
    """Folded away under the form: progress made before today. "Count from N weeks / months / days ago"
    moves the goal's start back (a habit's ticks or timetable hours from then count by themselves);
    a goal kept by hand also takes how much was done in that time. Returns (new start or None, amount)."""
    today = store.local_today()
    since = date.fromisoformat(goal["period_start"]) if goal else today
    with st.expander("Already made progress?", icon=":material/history:",
                     expanded=bool(st.session_state.get(f"{key}_ago_n"))):          # (stays open once filled in)
        if goal:
            st.caption(f"Counting from {store._short(since, since.year != today.year)}.")
        a, b = st.columns([1, 1.4])
        n = a.number_input("Count from", min_value=0, step=1, value=0, key=f"{key}_ago_n",
                           help="Move the goal's start back so what you did then counts")
        unit = b.selectbox("ago", list(EARLIER_UNITS), key=f"{key}_ago_unit")
        if not n:
            return None, 0.0
        start = _months_on(today, -n) if unit == "months" else today - timedelta(days=n * EARLIER_UNITS[unit])
        auto = store.counted_between(start, today, values["habit_id"], values["category_id"], values["label"])
        if auto is not None:
            what = f"{_num(auto)} {values['unit'] or ''}".strip()
            st.caption(f"From {store._short(start, start.year != today.year)}: {what} so far, counted automatically.")
            return start, 0.0
        done = st.number_input("Done in that time", min_value=0.0, step=1.0, value=0.0, format="%g",
                               key=f"{key}_ago_done")
        return start, done


def _new_goal():
    with st.popover("New goal", icon=":material/add:", width="stretch"):
        values = _goal_form("new_goal")
        if st.button("Add goal", key="new_goal_add", type="primary", disabled=not values or not values["title"]):
            g = store.add_goal(values["title"], None, values["start"] or store.local_today(), values["target"],
                               values["unit"], values["habit_id"], category_id=values["category_id"],
                               label=values["label"], due=max(values["due"], values["start"] or values["due"]))
            if values["earlier"]:
                store.set_goal_progress(g["id"], values["earlier"])
            for k in [k for k in st.session_state if k.startswith("new_goal_")]:
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
        if g["kind"] == "count":
            progress = st.number_input("Progress so far", min_value=0.0, step=1.0, value=float(g["progress"]), format="%g",
                                       key=f"{key}_progress")
        save, delete = st.columns(2)
        if save.button("Save", key=f"{key}_save", type="primary", width="stretch",
                       disabled=not values or not values["title"]):
            start, earlier = values.pop("start"), values.pop("earlier")
            first = start or date.fromisoformat(g["period_start"])
            values["due"] = max(values["due"], first)                     # (never before the day it counts from)
            store.update_goal(g["id"], **values, **({"start": start} if start else {}))
            for k in ("due", "ago_n", "ago_done"):
                st.session_state.pop(f"{key}_{k}", None)
            if g["kind"] == "count" and values["habit_id"] is None and values["category_id"] is None:
                store.set_goal_progress(g["id"], progress + earlier)
            st.rerun()
        if delete.button("Delete", key=f"{key}_delete", icon=":material/delete:", width="stretch"):
            undo.checkpoint(f"Deleted the goal '{g['title']}'")
            store.delete_goal(g["id"])
            st.rerun()


# ---------------------------------------------------------------------------
# Goals page
# ---------------------------------------------------------------------------

def _goal_row(g, ctx=None, neighbours=None):
    """One goal as a card: title, state badge, − / + (kept by hand) and ⋯; its number; the pace chart
    (from now on) or a bar (past goals); short detail lines, and this week's numbers for hours goals."""
    from venato import pace
    from venato.ui import goal_chart, goal_time
    p = pace.goal_pace(g, ctx) if ctx is not None else None
    with st.container(border=True, key=f"goal_card_{g['id']}"):
        text, minus, plus, more = st.columns([5, 1, 1, 1.4], vertical_alignment="center")
        badge = f"  \n{goal_time.badge(p['state'])}" if p and p["state"] != "upcoming" else ""
        text.markdown(f"**{goal_time.md(g['title'])}** :gray[{due_line(g)}]{badge}")
        if g["kind"] != "count":
            minus.empty()
            plus.empty()
        else:
            minus.button("", icon=":material/remove:", key=f"minus_{g['id']}", help=f"Take 1 off {g['title']}",
                         on_click=store.add_goal_progress, args=(g["id"], -1), disabled=g["value"] <= 0)
            plus.button("", icon=":material/add:", key=f"plus_{g['id']}", help=f"Add 1 to {g['title']}",
                        on_click=store.add_goal_progress, args=(g["id"], 1))
        with more:
            _edit_goal(g, neighbours)
        unit = f" {g['unit']}" if g["unit"] else ""
        st.markdown(f"### {_num(g['value'])} :gray[of {_num(g['target'])}{goal_time.md(unit)} · {round(100 * fraction(g))}%]")
        svg = goal_chart.chart(p, ctx) if p else ""
        if svg:
            st.html(svg)
        else:
            st.html(f'<div class="hg-bar">{_fill(g)}</div>' + BAR_CSS.replace("ACCENT", _accent()))
        lines = list(p.get("details") or []) if p else []
        week = goal_chart.week_line(p) if p else ""
        if week:
            lines.insert(0, week)
        if lines:
            st.caption("  \n".join(goal_time.md(x) for x in lines))
        if g["habit"]:
            st.caption(f":material/sync: Counted from the habit **{escape(g['habit'])}**")
        elif g["category"]:
            what = f"{g['label']} ({g['category']})" if g.get("label") else g["category"]
            st.caption(f":material/schedule: Counted from your timetable's Actual hours of **{escape(what)}**, "
                       "on days you've confirmed")


def due_line(g, today=None):
    """"by 31 Dec · 44 days left", "by 31 Oct · ended", "from 1 Dec, by 31 Dec"."""
    today = today or store.local_today()
    due, start = date.fromisoformat(g["due"]), date.fromisoformat(g["period_start"])
    left = (due - today).days
    when = store.goal_title_due(due, today)
    if start > today:
        return f"from {store._short(start, start.year != today.year)}, {when}"
    if left < 0:
        return f"{when} · ended"
    return f"{when} · " + ("due today" if left == 0 else "1 day left" if left == 1 else f"{left} days left")


def _section(today, ctx):
    goals = store.goals_open(today)
    done = sum(fraction(g) >= 1 for g in goals)
    with st.container(border=True):
        st.subheader(f"Goals :gray[{done}/{len(goals)}]", anchor=False)
        ids = [g["id"] for g in goals]
        cols = st.columns(2, gap="small")
        for i, g in enumerate(goals):
            with cols[i % 2]:
                _goal_row(g, ctx, ids)
        if not goals:
            st.caption("No goals yet.")
        _new_goal()
    past = store.goals_past(today)
    if past:
        with st.expander(f"Past goals ({sum(fraction(g) >= 1 for g in past)}/{len(past)} done)"):
            cols = st.columns(2, gap="small")
            for i, g in enumerate(past):
                with cols[i % 2]:
                    _goal_row(g)


def render_page():
    st.header("Goals", anchor=False)
    st.caption("Measurable targets, each with a deadline, and deadlines for work. Day-to-day to-dos live on Home.")
    today = store.local_today()
    from venato import pace
    from venato.ui import goal_time
    from venato.ui import goal_chart
    ctx = pace.Ctx()
    main, side = st.columns([2.3, 1], gap="medium")      # the side panel stacks under on narrow screens
    with main:
        st.html(goal_chart.legend())                    # once, for every goal's pace chart
        _section(today, ctx)
    with side:
        goal_time.free_split(ctx)                       # where this week's free time goes, by goal
        goal_time.offers(ctx)                           # "X can't be finished in time"
        goal_time.suggestions(ctx)
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
    text = f"Should be at {_num(round(should, 1))} of {_num(g['target'])} by today"
    return f'<span class="hg-mark" role="img" aria-label="{escape(text)}" title="{escape(text)}" style="left:{pct:.1f}%"></span>'


STATUS_ICON = {"done": "✓", "on_track": "✓", "behind": "⚠", "slipping": "⚠", "unreachable": "✕", "ended": "■",
               "upcoming": "○"}


def status_line(p):
    """One short line for Home: the state (icon + word, never colour alone) and how far off today's pace."""
    from venato import pace
    g, state = p["goal"], p["state"]
    text = pace.STATES[state]
    if state == "behind" and p["expected"] - p["value"] >= 0.05:
        text += f": {pace.amount(g, p['expected'] - p['value'])} under today's pace"
    elif state == "behind" and p.get("late"):
        text += f": {p['late']} days late at this rate"
    elif state == "slipping":
        text += ": done is trailing the Plan this week"
    elif state == "unreachable":
        text += ": not enough time left"
    return f"{STATUS_ICON[state]} {text}"


def render_home(ctx=None):
    """Home's Goals card (Home A): each current goal's bar with the "should be here by today" tick and one status line."""
    from venato import pace
    from venato.ui import appearance
    today = store.local_today()
    ctx = ctx or pace.Ctx()
    accent = _accent()
    warn, ok = ("#FBBF24", "#4ADE80") if appearance.is_dark() else ("#B45309", "#146C2E")
    tone = {"done": ok, "on_track": ok, "behind": warn, "slipping": warn, "unreachable": warn}
    rows = []
    for g in store.goals_active(today):
        pct = 100 * fraction(g)
        when = store.goal_title_due(g["due"], today)
        p = pace.goal_pace(g, ctx)
        rows.append(
            f'<div class="hg-row{" done" if pct >= 100 else ""}">'
            f'<div class="hg-top"><span class="hg-title">{escape(g["title"])}</span>'
            f'<span class="hg-when">{when}</span>'
            f'<span class="hg-amount">{"✓ " if pct >= 100 else ""}{escape(amount(g))}</span></div>'
            f'<div class="hg-track"><div class="hg-bar">{_fill(g)}</div>{_marker(g, today)}</div>'
            f'<div class="hg-status" style="color:{tone.get(p["state"], "inherit")}">{escape(status_line(p))}</div></div>'
        )
    with st.container(border=True, key="home_goals_card"):
        head = st.container(horizontal=True, vertical_alignment="center")
        head.markdown("**Goals**", width="stretch")
        head.button("See all", key="home_goals_all", type="tertiary", on_click=_go_to_goals)
        body = "".join(rows) or '<div class="hg-empty">No goals yet.</div>'
        st.html(f"""<style>
          .hg {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 10px 28px; }}  /* two-up when wide */
          .hg-top {{ display: flex; align-items: baseline; gap: 8px; font-size: 0.88rem; margin-bottom: 4px; }}
          .hg-title {{ font-weight: 600; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
          .hg-when {{ font-size: 0.72rem; opacity: 0.78; white-space: nowrap; }}
          .hg-amount {{ margin-left: auto; opacity: 0.8; font-variant-numeric: tabular-nums; white-space: nowrap; }}
          .hg-row.done .hg-amount {{ color: {accent}; opacity: 1; font-weight: 600; }}
          .hg-status {{ font-size: 0.8rem; margin-top: 3px; }}
          .hg-empty {{ opacity: 0.78; font-size: 0.86rem; }}
          .hg-track {{ position: relative; }}
          .hg-mark {{ position: absolute; top: -4px; width: 2px; height: 15px; margin-left: -1px; border-radius: 1px;
                      background: currentColor; opacity: 0.85; }}
        </style><div class="hg">{body}</div>""" + BAR_CSS.replace("ACCENT", accent))
