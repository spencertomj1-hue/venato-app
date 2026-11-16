"""
Goals for a month or a year. Two kinds:
- simple (the default): something to achieve, ticked off once ("Sub 19:30 5 km",
  "Get 100 users on Venato");
- target: a number to reach ("Gym: 12 sessions"), with a progress bar, updated by
  hand (− / + / a number) or counted automatically from a habit's ticks.

The Goals page lists this month's and this year's goals (with ‹ › to look at
other months and years); Home shows the current ones as a compact list of bars.
"""

from html import escape

import streamlit as st

from venato import store
from venato import undo

PAGE = "Goals"                                  # sidebar label (also what "See all" switches to)
NAMES = {"monthly": "Monthly", "yearly": "Yearly"}
CURRENT = {"monthly": "This month", "yearly": "This year"}
BY_HAND, BY_HABIT = "Update it myself", "Count a habit's ticks"
SIMPLE, NUMBER = "Something to achieve", "Reach a number"


def _num(x):
    return f"{store._num(x):g}" if isinstance(x, float) else str(x)


def amount(g):
    """"7 / 12 sessions" ("Done" / "Not yet" for a simple goal)."""
    if g["kind"] == "simple":
        return "Done" if g["done"] else "Not yet"
    return f"{_num(g['value'])} / {_num(g['target'])}" + (f" {g['unit']}" if g["unit"] else "")


def fraction(g):
    return min(g["value"] / g["target"], 1.0) if g["target"] else 0.0


def _start_key(period):
    return f"goals_start_{period}"


def _shift(period, n):
    """‹ / › / back to the current month or year."""
    key = _start_key(period)
    if n == 0:
        st.session_state[key] = store.start_of_period(period, store.local_today())
    else:
        st.session_state[key] = store.shift_period(period, st.session_state[key], n)


def _go_to_goals():
    st.session_state["page"] = PAGE        # the sidebar radio's key; button callbacks run before it's drawn


# ---------------------------------------------------------------------------
# The form shared by "New goal" and "Edit"
# ---------------------------------------------------------------------------

def _goal_form(key, goal=None):
    """Title, target, unit and how progress is tracked. Returns the values, or None if the habit choice is missing."""
    habits = dict(store.get_habits())                       # id -> name
    simple = (goal["kind"] == "simple") if goal else True
    kind = st.radio("Kind", [SIMPLE, NUMBER], index=0 if simple else 1, key=f"{key}_kind", horizontal=True,
                    label_visibility="collapsed")
    title = st.text_input("Goal", value=goal["title"] if goal else "", key=f"{key}_title",
                          placeholder="e.g. Sub 19:30 5 km" if kind == SIMPLE else "e.g. Gym")
    if kind == SIMPLE:
        return {"title": title.strip(), "kind": "simple", "target": 1, "unit": None, "habit_id": None}
    a, b = st.columns(2)
    target = a.number_input("Target", min_value=0.5, step=1.0,
                            value=float(goal["target"]) if goal and goal["kind"] != "simple" else 10.0, format="%g",
                            key=f"{key}_target")
    unit = b.text_input("Unit (optional)", value=(goal["unit"] or "") if goal else "", key=f"{key}_unit",
                        placeholder="sessions, km, books…")
    linked = bool(goal and goal["habit_id"] is not None)
    how = st.radio("Progress", [BY_HAND, BY_HABIT], index=1 if linked else 0, key=f"{key}_how", horizontal=True,
                   help="Count a habit's ticks: every day you tick that habit in the period adds 1.")
    habit_id = None
    if how == BY_HABIT:
        if not habits:
            st.caption("You have no habits yet. Add one on the Daily Log page, or update this goal yourself.")
            return None
        ids = list(habits)
        habit_id = st.selectbox("Habit", ids, format_func=habits.get, key=f"{key}_habit",
                                index=ids.index(goal["habit_id"]) if linked and goal["habit_id"] in ids else 0)
    return {"title": title.strip(), "kind": "target", "target": target, "unit": unit.strip() or None, "habit_id": habit_id}


def _new_goal(period, start):
    with st.popover("New goal", icon=":material/add:", width="stretch"):
        values = _goal_form(f"new_{period}")
        category = _category_picker(f"new_{period}", None)
        if st.button("Add goal", key=f"new_{period}_add", type="primary", disabled=not values or not values["title"]):
            goal = store.add_goal(values["title"], period, start, values["target"], values["unit"], values["habit_id"],
                                  kind=values["kind"])
            if category:
                store.set_goal_category(goal["id"], category)
            for k in [k for k in st.session_state if k.startswith(f"new_{period}_")]:
                del st.session_state[k]                      # an empty form next time
            st.rerun()


NO_CATEGORY, NEW_CATEGORY = "No category", "+ New category…"


def _category_picker(key, current):
    """A goal category (each has its own colour). Returns the name, '' for none."""
    cats = list(store.goal_categories())
    options = [NO_CATEGORY, *cats, NEW_CATEGORY]
    choice = st.selectbox("Category", options, key=f"{key}_cat",
                          index=options.index(current) if current in cats else 0,
                          help="Goals in a category are grouped together on Home, in its colour.")
    if choice == NEW_CATEGORY:
        return st.text_input("New category name", key=f"{key}_catnew", placeholder="e.g. Work").strip()
    return "" if choice == NO_CATEGORY else choice


def _edit_goal(g):
    with st.popover("", icon=":material/more_horiz:", help="Edit or delete"):
        key = f"edit_{g['id']}"
        values = _goal_form(key, g)
        category = _category_picker(key, g.get("category"))
        if category and category in store.goal_categories():
            colour = st.color_picker("Category colour", store.goal_categories()[category], key=f"{key}_catcol")
            if colour != store.goal_categories()[category]:
                store.set_goal_category_colour(category, colour)
        progress = None
        if not g["habit"] and g["kind"] != "simple" and values and values["kind"] != "simple":
            progress = st.number_input("Progress so far", min_value=0.0, step=1.0, value=float(g["progress"]), format="%g",
                                       key=f"{key}_progress")
        save, delete = st.columns(2)
        if save.button("Save", key=f"{key}_save", type="primary", width="stretch",
                       disabled=not values or not values["title"]):
            store.update_goal(g["id"], **values)
            store.set_goal_category(g["id"], category)
            if progress is not None and values["habit_id"] is None:
                store.set_goal_progress(g["id"], progress)
            st.rerun()
        if delete.button("Delete", key=f"{key}_delete", icon=":material/delete:", width="stretch"):
            undo.checkpoint(f"Deleted the goal '{g['title']}'")
            store.delete_goal(g["id"])
            st.rerun()


# ---------------------------------------------------------------------------
# Goals page
# ---------------------------------------------------------------------------

def _tick(goal_id, key):
    store.set_goal_done(goal_id, st.session_state[key])


def _done_on(g):
    """'4 Nov' from the goal's done_at timestamp."""
    if not g.get("done_at"):
        return ""
    d = store._as_date(g["done_at"][:10])
    return f"{d.day} {d:%b}"


def _simple_row(g):
    with st.container(border=True):
        tick, more = st.columns([7, 1.4], vertical_alignment="center")
        key = f"goal_done_{g['id']}"
        label = f"**{g['title']}**" + (f"  \n:gray[Achieved {_done_on(g)}]" if g["done"] and g.get("done_at") else "")
        tick.checkbox(label, value=g["done"], key=key, on_change=_tick, args=(g["id"], key))
        with more:
            _edit_goal(g)


def _goal_row(g):
    if g["kind"] == "simple":
        _simple_row(g)
        return
    with st.container(border=True):
        text, minus, plus, more = st.columns([5, 1, 1, 1.4], vertical_alignment="center")
        pct = round(100 * fraction(g))
        cat = f" · {escape(g['category'])}" if g.get("category") else ""
        text.markdown(f"**{escape(g['title'])}**  \n:gray[{escape(amount(g))} · {pct}%{cat}]")
        if g["habit"]:
            minus.empty()
            plus.empty()
        else:
            minus.button("", icon=":material/remove:", key=f"minus_{g['id']}", help="Take 1 off",
                         on_click=store.add_goal_progress, args=(g["id"], -1), disabled=g["value"] <= 0)
            plus.button("", icon=":material/add:", key=f"plus_{g['id']}", help="Add 1",
                        on_click=store.add_goal_progress, args=(g["id"], 1))
        with more:
            _edit_goal(g)
        st.html(f'<div class="hg-bar">{_fill(g)}</div>' + BAR_CSS.replace("ACCENT", _colour(g)))
        if g["habit"]:
            st.caption(f":material/sync: Counted from the habit **{escape(g['habit'])}**")


def _section(period, today):
    start = st.session_state.setdefault(_start_key(period), store.start_of_period(period, today))
    current = start == store.start_of_period(period, today)
    goals = store.goals_in(period, start)
    done = sum(fraction(g) >= 1 for g in goals)
    with st.container(border=True):
        st.subheader(f"{NAMES[period]} :gray[{done}/{len(goals)}]", anchor=False)
        prev, label, nxt, back = st.columns([1, 4, 1, 3], vertical_alignment="center")
        prev.button("", icon=":material/chevron_left:", key=f"prev_{period}", on_click=_shift, args=(period, -1),
                    help=f"Previous {'month' if period == 'monthly' else 'year'}")
        label.markdown(f"**{store.period_title(period, start, today)}**")
        nxt.button("", icon=":material/chevron_right:", key=f"next_{period}", on_click=_shift, args=(period, 1),
                   help=f"Next {'month' if period == 'monthly' else 'year'}")
        if not current:
            back.button(CURRENT[period], key=f"now_{period}", on_click=_shift, args=(period, 0))
        for g in goals:
            _goal_row(g)
        if not goals:
            st.caption("No goals yet.")
        _new_goal(period, start)


def render_page():
    st.header("Goals", anchor=False)
    st.caption("Measurable targets for the month or year, and deadlines. Day-to-day to-dos live on Home.")
    today = store.local_today()
    for col, period in zip(st.columns(2, gap="medium"), store.GOAL_PERIODS):
        with col:
            _section(period, today)
    from venato.ui import deadlines
    deadlines.render_section()


# ---------------------------------------------------------------------------
# Home: this month's and this year's goals as progress bars
# ---------------------------------------------------------------------------

def _accent():
    return st.get_option("theme.primaryColor") or "#ff4b4b"


def _colour(g):
    """A goal's bar colour: its category's, else the app's accent."""
    return store.goal_categories().get(g.get("category") or "", None) or _accent()


def _fill(g, colour=None):
    style = f"width:{100 * fraction(g):.1f}%" + (f";background:{colour}" if colour else "")
    return f'<i style="{style}"></i>'


# The progress bar used on both pages, in the app's accent colour (st.progress has its own colour).
BAR_CSS = """<style>
  .hg-bar { height: 7px; border-radius: 999px; background: rgba(128, 128, 128, 0.18); overflow: hidden; }
  .hg-bar i { display: block; height: 100%; border-radius: 999px; background: ACCENT; transition: width 0.4s ease; }
</style>"""


CHECK = ('<svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5" '
         'fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/></svg>')


def bar_row(title, when, amount_text, frac, colour):
    """One Home progress row: title, period, amount and a bar (shared with Km run)."""
    done = frac >= 1
    return (f'<div class="hg-row{" done" if done else ""}">'
            f'<div class="hg-top"><span class="hg-title">{escape(title)}</span>'
            f'<span class="hg-when">{escape(when)}</span>'
            f'<span class="hg-amount">{CHECK if done else ""}{escape(amount_text)}</span></div>'
            f'<div class="hg-bar"><i style="width:{100 * min(frac, 1):.1f}%;background:{colour}"></i></div></div>')


def home_css(accent):
    return f"""<style>
      .hg {{ display: grid; gap: 9px; }}
      .hg-top {{ display: flex; align-items: baseline; gap: 8px; font-size: 0.86rem; margin-bottom: 3px; }}
      .hg-title {{ font-weight: 600; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
      .hg-when {{ font-size: 0.72rem; opacity: 0.78; white-space: nowrap; }}
      .hg-amount {{ margin-left: auto; display: inline-flex; align-items: center; gap: 4px; opacity: 0.75;
                    font-variant-numeric: tabular-nums; white-space: nowrap; }}
      .hg-row.done .hg-amount {{ color: {accent}; opacity: 1; font-weight: 600; }}
      .hg-empty {{ opacity: 0.6; font-size: 0.86rem; }}
      .hg-cat {{ display: flex; align-items: center; gap: 7px; margin-top: 4px; font-size: 0.74rem; font-weight: 700;
                 letter-spacing: .08em; text-transform: uppercase; }}
      .hg-cat i {{ width: 10px; height: 10px; border-radius: 3px; }}
    </style>""" + BAR_CSS.replace("ACCENT", accent)


def render_home():
    today = store.local_today()
    accent = _accent()
    cats = store.goal_categories()
    groups = {}                                  # category ("" = none) -> rows; categories in their order
    simple = []
    for period in store.GOAL_PERIODS:
        for g in store.goals_in(period, today):
            when = "this month" if period == "monthly" else "this year"
            if g["kind"] == "simple":
                simple.append((g, when))
                continue
            cat = g.get("category") if g.get("category") in cats else ""
            groups.setdefault(cat, []).append(bar_row(g["title"], when, amount(g), fraction(g), cats.get(cat, accent)))
    rows = []
    for cat in [c for c in cats if c in groups] + ([""] if "" in groups else []):
        if cat:
            rows.append(f'<div class="hg-cat"><i style="background:{cats[cat]}"></i>{escape(cat)}</div>')
        rows += groups[cat]
    head, link = st.columns([4, 1], vertical_alignment="center")
    head.markdown("**Goals**")
    link.button("See all", key="home_goals_all", type="tertiary", on_click=_go_to_goals)
    for g, when in simple:
        key = f"home_goal_{g['id']}"
        st.checkbox(f"{g['title']} :gray[· {when}]", value=g["done"], key=key, on_change=_tick, args=(g["id"], key))
    if simple and not rows:
        return
    body = "".join(rows) or '<div class="hg-empty">No goals for this month or year yet.</div>'
    st.html(home_css(accent) + f'<div class="hg">{body}</div>')
