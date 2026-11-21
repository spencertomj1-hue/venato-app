"""
The Home page's to-do lists: today's, this week's and this month's, in one
card with a Daily / Weekly / Monthly switch (one list at a time). This is the Python side of the to-do list component
(todos_component.js/.css).

The component draws Apple Reminders-style lists and applies edits straight
away; the ops it sends are saved here with the store and acknowledged in
`acked`, the same pattern as the timetable grid.
"""

from pathlib import Path

import streamlit as st

from venato import store
from venato.ui import kit

HERE = Path(__file__).parent

HOME_LIMIT = 6        # to-dos shown in a list before "N more"

_todos_component = st.components.v2.component(
    "venato_todos",
    html='<div class="gl-root"></div>',
    css=(HERE / "components" / "todos_component.css").read_text(encoding="utf-8"),
    js=(HERE / "components" / "todos_component.js").read_text(encoding="utf-8"),
)


def apply_op(op):
    """
    Save one op from a to-do list:
      {kind: "add", goal: {id, title, period, period_start}}
      {kind: "toggle", id, done}        {kind: "edit", id, title | notes}
      {kind: "repeat", id, repeat}      {kind: "move", id, period}
      {kind: "delete", id}              {kind: "reorder", ids}
    """
    kind = op["kind"]
    if kind == "add":
        t = op["goal"]
        if t["title"].strip():
            store.add_todo(t["title"], t["period"], t["period_start"], todo_id=t["id"])   # idempotent per id
    elif kind == "toggle":
        store.set_todo_done(op["id"], op["done"])
    elif kind == "edit":
        changes = {k: op[k] for k in ("title", "notes") if k in op}
        if changes.get("title", "x").strip():
            store.update_todo(op["id"], **changes)
    elif kind == "repeat":
        store.update_todo(op["id"], repeat=op["repeat"])
    elif kind == "move":
        store.move_todo(op["id"], op["period"])
    elif kind == "delete":
        t = store.get_todo(op["id"])
        from venato import undo
        undo.checkpoint(f"Deleted the to-do '{t['title']}'" if t else "Deleted a to-do")
        store.delete_todo(op["id"])
    elif kind == "reorder":
        store.reorder_todos(op["ids"])


def _changed(op):
    """kit.rerun_app_if tags for an op: a delete also saves an Undo point (the Undo bar is the app's)."""
    return {f"todo:{op.get('id') or op.get('goal', {}).get('id')}"} | ({"undo"} if op["kind"] == "delete" else set())


def _on_ops(key="home_todos"):
    """Save new ops and remember them as acknowledged. Only the to-do list reruns, unless the app shows
    something that changed (kit.rerun_app_if)."""
    ops = st.session_state[key]["ops"] or []
    acked = st.session_state.setdefault("todo_acked", [])
    new_ops = [op for op in ops if op["opId"] not in acked]
    for op in new_ops:
        apply_op(op)
    # Keep the list short; a list only ever has a few ops in flight.
    st.session_state["todo_acked"] = (acked + [op["opId"] for op in new_ops])[-500:]
    kit.rerun_app_if(set().union(*(_changed(op) for op in new_ops)))


@st.fragment
def render_home():
    """Today's, this week's and this month's to-dos: one card, its header switching between the lists
    (the tile header names it; the component draws the switch and starts on the first list with open to-dos)."""
    store.roll_todos()
    today = store.local_today()
    sections = []
    for period in store.TODO_PERIODS:
        start = store.start_of_period(period, today)
        sections.append({"period": period, "start": start.isoformat(),
                         "title": store.period_title(period, start, today),
                         "goals": store.todos_for(period, start), "limit": HOME_LIMIT})
    with st.container(border=True, key="home_todos_card"):
        data = {"today": today.isoformat(), "sections": sections, "tile": True,
                "acked": st.session_state.get("todo_acked", [])}
        _todos_component(data=data, key="home_todos", on_ops_change=_on_ops)


# ---------------------------------------------------------------------------
# The To-dos page (Home's To-dos tile opens it): one list at a time, Today / This week / This month
# ---------------------------------------------------------------------------

TABS = {"Today": "daily", "This week": "weekly", "This month": "monthly"}


def _section(period, today, limit=None):
    start = store.start_of_period(period, today)
    return {"period": period, "start": start.isoformat(), "title": store.period_title(period, start, today),
            "goals": store.todos_for(period, start), "limit": limit}


@st.fragment
def _page_list(period):
    today = store.local_today()
    with st.container(border=True, key="todos_page_card"):
        data = {"today": today.isoformat(), "sections": [_section(period, today)], "single": True,
                "acked": st.session_state.get("todo_acked", [])}
        _todos_component(data=data, key=f"page_todos_{period}", on_ops_change=lambda: _on_ops(f"page_todos_{period}"))


def render_page():
    store.roll_todos()
    today = store.local_today()
    from venato import tile_status
    head = st.container(horizontal=True, vertical_alignment="center", key="todos_head")
    with head:
        from venato.ui import nav
        st.markdown(nav.icon_md(":material/check:", nav.COLOURS["To-dos"], "vn-page-icon"), unsafe_allow_html=True,
                    width="content")
        with st.container(gap=None, width="stretch"):
            st.header("To-dos", anchor=False)
            st.caption(f"Today · {tile_status.todos(today)}")
        tab = st.segmented_control("Which list", list(TABS), default="Today", key="todos_tab",
                                   label_visibility="collapsed", width="content")
    period = TABS.get(tab or "Today", "daily")
    main, side = st.columns([2, 1], gap="medium")
    with main:
        _page_list(period)
    with side:
        from venato import blocks
        if blocks.is_on("goals"):
            with st.container(border=True):
                from venato.ui import deadlines
                deadlines.render_home()
        if period == "daily":
            week = [t for t in store.todos_for("weekly", today) if not t["done"]]
            with st.container(border=True, key="todos_later"):
                kit.subhead("Later this week")
                if not week:
                    st.caption("Nothing else on this week's list.")
                for t in week[:8]:
                    st.markdown(kit.md(t["title"]))
