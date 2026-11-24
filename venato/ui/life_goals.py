"""
The Goals page's long-term goals: one card each (title, time left, why, an overall bar), opening to its
targets (the measurable ones, drawn by goals.py as before) and its to-dos (tick, add). Also "New goal",
each goal's ⋯ (edit, move, archive, delete), and Home's Goals tile rows.
"""

from datetime import date
from html import escape

import streamlit as st

from venato import regional
from venato import store
from venato import undo
from venato.ui import kit

HORIZON_LABELS = {3: "3 months", 6: "6 months", 12: "12 months"}
CUSTOM = "Pick an end date"


def _span_form(key, g=None):
    """Start, and how long: 3 / 6 / 12 months or an end date. Returns (start, months or None, end or None)."""
    today = store.local_today()
    start = date.fromisoformat(g["start"]) if g else today
    if g:
        start = st.date_input("Starts", value=start, key=f"{key}_start", format=regional.input_format())
    horizon = store.horizon_of(g) if g else 6
    options = list(HORIZON_LABELS.values()) + [CUSTOM]
    pick = st.segmented_control("How long", options, key=f"{key}_horizon",
                                default=HORIZON_LABELS.get(horizon, CUSTOM) if (g or horizon) else options[1])
    if pick == CUSTOM:
        end = date.fromisoformat(g["end_date"]) if g else store.months_on(today, 6)
        end = st.date_input("Ends", value=end, min_value=start, key=f"{key}_end", format=regional.input_format())
        return start, None, end
    months = next((n for n, text in HORIZON_LABELS.items() if text == pick), 6)
    st.caption(f"Until {regional.short_date(store.months_on(start, months), today)}")
    return start, months, None


def _clear(key):
    for k in [k for k in st.session_state if k.startswith(f"{key}_")]:
        del st.session_state[k]


def new_goal():
    """The "New goal" button and its form."""
    key = "new_life"
    with st.popover("New goal", icon=":material/flag:", width="stretch", type="primary"):
        title = st.text_input("Goal", key=f"{key}_title", placeholder="e.g. Get fit, Land a grad job")
        why = st.text_input("Why it matters (optional)", key=f"{key}_why", placeholder="e.g. Feel strong for the season")
        start, months, end = _span_form(key)
        if st.button("Add goal", key=f"{key}_add", type="primary", disabled=not title.strip()):
            store.add_life_goal(title, months=months, end=end, start=start, why=why)
            _clear(key)
            st.rerun()


def _move(ids, gid, step):
    i = ids.index(gid)
    j = i + step
    if 0 <= j < len(ids):
        ids = list(ids)
        ids[i], ids[j] = ids[j], ids[i]
        store.reorder_life_goals(ids)


def _colour_picker(g, key):
    """The goal's colour: a row of swatches (GOAL_COLOURS), saved as soon as one is picked; its to-dos' dots,
    Home's tile and this card follow."""
    now = store.life_goal_colour(g["id"]).upper()
    st.caption("Colour")
    css = []
    with st.container(horizontal=True, gap="small"):
        for i, c in enumerate(store.GOAL_COLOURS):
            k = f"{key}_colour_{i}"
            ring = f"box-shadow: 0 0 0 2px var(--background-color, #fff), 0 0 0 4px {c};" if c == now else ""
            css.append(f".st-key-{k} button {{ background: {c} !important; border: 0 !important; width: 28px; "
                       f"height: 28px; min-height: 28px; padding: 0; border-radius: 50%; color: #fff !important; {ring} }}")
            st.button("✓" if c == now else "", key=k, help=store.GOAL_COLOUR_NAMES[c],
                      on_click=store.set_life_goal_colour, args=(g["id"], c))
    st.html(f"<style>{' '.join(css)}</style>")


def _edit(g, ids):
    key = f"life_{g['id']}"
    with st.popover("", icon=":material/more_horiz:", help="Edit, move, archive or delete"):
        if len(ids) > 1:
            up, down = st.columns(2)
            up.button("Move up", icon=":material/arrow_upward:", key=f"{key}_up", width="stretch",
                      disabled=ids[0] == g["id"], on_click=_move, args=(ids, g["id"], -1))
            down.button("Move down", icon=":material/arrow_downward:", key=f"{key}_down", width="stretch",
                        disabled=ids[-1] == g["id"], on_click=_move, args=(ids, g["id"], 1))
        title = st.text_input("Goal", value=g["title"], key=f"{key}_title")
        why = st.text_input("Why it matters (optional)", value=g["why"] or "", key=f"{key}_why")
        _colour_picker(g, key)
        start, months, end = _span_form(key, g)
        save, archive, delete = st.columns(3)
        if save.button("Save", key=f"{key}_save", type="primary", width="stretch", disabled=not title.strip()):
            try:
                store.update_life_goal(g["id"], title=title, why=why, start=start, months=months,
                                       **({} if months else {"end": end}))
            except ValueError as e:
                st.error(str(e))
            else:
                _clear(key)
                st.rerun()
        if archive.button("Unarchive" if g["archived"] else "Archive", key=f"{key}_archive", width="stretch",
                          icon=":material/inventory_2:", help="Done with it: it moves to Past goals"):
            store.update_life_goal(g["id"], archived=not g["archived"])
            st.rerun()
        if delete.button("Delete", key=f"{key}_delete", icon=":material/delete:", width="stretch",
                         help="Its targets and to-dos stay, under no goal"):
            undo.checkpoint(f"Deleted the goal '{g['title']}'")
            store.delete_life_goal(g["id"])
            st.rerun()


def bar_html(frac, label="", colour=None):
    """A goal's overall bar, in its colour (else the theme's accent)."""
    from venato.ui.goals import BAR_CSS, _accent
    fill = f";background:{colour}" if colour else ""
    return (f'<div class="hg-bar" role="img" aria-label="{escape(label)}"><i style="width:{100 * frac:.1f}%{fill}"></i></div>'
            + BAR_CSS.replace("ACCENT", _accent()))


def summary(p):
    """"2 of 3 targets hit · 4 of 7 to-dos done"."""
    bits = []
    if p["targets"]:
        bits.append(f"{p['targets_done']} of {p['targets']} target{'s' if p['targets'] != 1 else ''} hit")
    if p["todos"]:
        bits.append(f"{p['todos_done']} of {p['todos']} to-do{'s' if p['todos'] != 1 else ''} done")
    return " · ".join(bits) or "Nothing under it yet: add a target or a to-do"


def _todos(g, today):
    """The goal's to-dos: open ones to tick, a line to add one, done ones counted."""
    todos = store.life_goal_todos(g["id"])
    open_ = [t for t in todos if not t["done"]]
    kit.subhead("To-dos", icon=":material/check_box:")
    for t in open_:
        when = f" :gray[· due {regional.short_date(t['due'], today)}]" if t.get("due") else ""
        st.checkbox(f"{kit.md(t['title'])}{when}", value=False, key=f"life_todo_{t['id']}",
                    on_change=store.set_todo_done, args=(t["id"], True))
    done = len(todos) - len(open_)
    if done:
        st.caption(f"{done} done")
    if not todos:
        st.caption("No to-dos yet.")
    key = f"life_{g['id']}_newtodo"
    with st.container(horizontal=True, vertical_alignment="bottom"):
        title = st.text_input("New to-do", key=key, placeholder="Add a to-do", label_visibility="collapsed",
                              width="stretch")
        if st.button("", icon=":material/add:", key=f"{key}_add", help="Add this to-do to the goal",
                     disabled=not (title or "").strip()):
            store.add_detailed_todo(title.strip(), group_id=store.ensure_life_goal_group(g["id"]))
            del st.session_state[key]
            st.rerun()


def card(g, ids, ctx, today, expanded=False):
    """One long-term goal: its header and bar, then its targets and to-dos."""
    from venato.ui import goals as goals_ui
    targets = store.life_goal_targets(g["id"])
    p = store.life_goal_progress(g["id"], targets=targets)
    with st.container(border=True, key=f"life_card_{g['id']}"):
        text, more = st.columns([8, 1], vertical_alignment="center")
        span = f"{regional.short_date(g['start'], today)} to {regional.short_date(g['end_date'], today)}"
        dot = f'<span style="color:{store.life_goal_colour(g["id"])}" aria-hidden="true">●</span> '
        text.markdown(f"#### {dot}{kit.md(g['title'])}\n:gray[{store.time_left(g, today)} · {span}]",
                      unsafe_allow_html=True)
        with more:
            _edit(g, ids)
        if g["why"]:
            st.caption(f":material/format_quote: {kit.md(g['why'])}")
        st.html(bar_html(p["fraction"], f"{g['title']}: {round(100 * p['fraction'])}%", store.life_goal_colour(g["id"])))
        st.caption(f"{round(100 * p['fraction'])}% · {summary(p)}")
        with st.expander("Targets and to-dos", expanded=expanded):
            kit.subhead("Targets", icon=":material/track_changes:")
            neighbours = [t["id"] for t in targets]
            for t in targets:
                goals_ui._goal_row(t, ctx if t["due"] >= today.isoformat() else None, neighbours)
            goals_ui._new_goal(key=f"new_goal_{g['id']}", life_goal_id=g["id"])
            _todos(g, today)


def render_section(ctx, today):
    """Every running goal as a card (the first one open), then "New goal" and the past ones folded away."""
    goals = store.life_goals(today)
    ids = [g["id"] for g in goals]
    for i, g in enumerate(goals):
        card(g, ids, ctx, today, expanded=i == 0)
    if not goals:
        st.caption("No goals yet. A goal is a plan for the next 3, 6 or 12 months: put targets "
                   "(measurable, with a date) and to-dos under it.")
    new_goal()
    past = store.life_goals_past(today)
    if past:
        with st.expander(f"Past goals ({len(past)})"):
            for g in past:
                card(g, [g["id"]], None, today)


BEHIND_BY = 0.05          # a goal more than 5 points under its pace counts as behind


def expected_fraction(g, targets, today):
    """Where an even pace would have a goal by today (0..1): the mean of its targets' (each capped at 100%),
    or with no targets, how much of its span has gone."""
    from venato import pace
    sized = [t for t in targets if t["target"]]
    if sized:
        return sum(min(pace.expected(t, today) / t["target"], 1.0) for t in sized) / len(sized)
    start, end = store._as_date(g["start"]), store._as_date(g["end_date"])
    total = (end - start).days + 1
    return min(1.0, max(0, (today - start).days) / total) if total > 0 else 0.0


def home_rows(today=None, todos=0):
    """Home's Goals tile, one dict per running goal in order: goal, colour, progress, fraction, expected (the
    pace tick), behind, next (the nearest open target or None), targets, and up to `todos` open to-dos."""
    today = today or store.local_today()
    colours = store.life_goal_colours()
    rows = []
    for g in store.life_goals(today):
        targets = store.life_goal_targets(g["id"])
        p = store.life_goal_progress(g["id"], targets=targets)
        nxt = next((t for t in targets if t["due"] >= today.isoformat()
                    and (not t["target"] or t["value"] < t["target"])), None)
        exp = expected_fraction(g, targets, today)
        rows.append({"goal": g, "colour": colours.get(g["id"]) or store.GOAL_COLOURS[0], "progress": p,
                     "fraction": p["fraction"], "expected": exp, "behind": p["fraction"] < exp - BEHIND_BY,
                     "next": nxt, "targets": targets,
                     "todos": store.life_goal_todos(g["id"], open_only=True)[:todos] if todos else []})
    return rows
