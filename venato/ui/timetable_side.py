"""
Timetable's side panel: your open to-dos and your goals, ready to be given time.

Pick one (it lights up), then drag on the week (or click a slot) to place it: the block takes its name and a
category, and is linked to it (store/links.py). A click without a drag gives a to-do the time it says it takes
(else 30 min) and a goal an hour.
  - A to-do is placed once (then put down). With no due day it gets the block's day. Marking the block done
    ticks the to-do.
  - A goal stays picked, for several sittings. One counted in hours gets the time straight away (its
    category and activity are the block's); one counted by hand goes up one each time a sitting is marked done.
Goals that count a habit's ticks aren't listed: time on the timetable doesn't move them.
Esc, a click on the picked one again, or picking a category on the grid puts it down.
"""

import math
import uuid

import streamlit as st

from venato import pace
from venato import store
from venato.ui import kit

GOAL_SLOTS = 2              # a click (no drag) gives a goal an hour


def _picked():
    return st.session_state.get("tt_pick") or {}


def _toggle(pick):
    """Pick it (a fresh nonce, so the grid takes it even if it was picked before), or put it down."""
    now = _picked()
    if now.get("kind") == pick["kind"] and now.get("id") == pick["id"]:
        st.session_state.pop("tt_pick", None)
    else:
        st.session_state["tt_pick"] = {**pick, "nonce": uuid.uuid4().hex[:10]}


def _todo_pick(t, cats, label_map):
    minutes = t.get("minutes") or store.TODO_MINUTES
    return {"kind": "todo", "id": t["id"], "label": t["title"], "once": True,
            "categoryId": store.match_category(t["title"], label_map, cats),
            "slots": max(1, math.ceil(minutes / 30))}


def _goal_pick(g, cats, label_map):
    hours = g["kind"] == "hours"
    label = (g.get("label") or g["title"]) if hours else g["title"]
    return {"kind": "goal", "id": g["id"], "label": label, "once": False, "slots": GOAL_SLOTS,
            "categoryId": g["category_id"] if hours else store.match_category(g["title"], label_map, cats)}


def _goal_text(g):
    if g["kind"] == "hours":
        return f"{pace.fmt(g['value'])} of {pace.fmt(g['target'])} h"
    unit = f" {g['unit']}" if g.get("unit") else ""
    return f"{pace.fmt(g['value'])} of {pace.fmt(g['target'])}{unit}"


def _item(key, pick, text, sub, picked):
    on = picked.get("kind") == pick["kind"] and picked.get("id") == pick["id"]
    st.button(text, key=key, on_click=_toggle, args=(pick,), type="primary" if on else "secondary",
              width="stretch", icon=":material/check_circle:" if on else None,
              help=f"{'Put down' if on else 'Pick'} {pick['label']}" + (f" · {sub}" if sub else ""))


def _style():
    st.html("""<style>
    .st-key-tt_side { gap: 0.4rem; }
    .st-key-tt_side [class*="st-key-tt_pick_"] button { justify-content: flex-start; text-align: left; min-height: 40px; }
    .st-key-tt_side [class*="st-key-tt_pick_"] button p { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .st-key-tt_side [class*="st-key-tt_pick_"] button > div { justify-content: flex-start !important; min-width: 0; }
    </style>""")


def render(ctx=None):
    """The panel beside the week: a hint for what's picked, then To-dos, then Goals."""
    _style()
    picked = _picked()
    cats, label_map = store.load_categories(), store.load_label_map()
    with st.container(border=True, key="tt_side"):
        kit.subhead("Give it time")
        if picked:
            st.caption(f":material/touch_app: Drag on the week to place **{kit.md(picked['label'])}**. "
                       "Esc puts it down.")
        else:
            st.caption("Pick a to-do or goal, then drag on the week to put it in.")

        kit.subhead("To-dos", icon=":material/check_box:")
        todos = store.open_todos(ctx.today if ctx else None)
        if not todos:
            st.caption("No open to-dos.")
        for t in todos:
            pick = _todo_pick(t, cats, label_map)
            mins = t.get("minutes")
            sub = f"{mins} min" if mins else ""
            _item(f"tt_pick_todo_{t['id']}", pick, t["title"] + (f" · {sub}" if sub else ""), sub, picked)

        kit.subhead("Goals", icon=":material/flag:")
        goals = [g for g in store.goals_open(ctx.today if ctx else None) if g["kind"] != "habit"]
        if not goals:
            st.caption("No goals to give time to.")
        for g in goals:
            sub = _goal_text(g)
            _item(f"tt_pick_goal_{g['id']}", _goal_pick(g, cats, label_map), f"{g['title']} · {sub}", sub, picked)
