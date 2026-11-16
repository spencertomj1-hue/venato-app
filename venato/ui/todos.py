"""
The Home page's to-do lists: today's, this week's and this month's, as three
compact cards. This is the Python side of the to-do list component
(todos_component.js/.css).

The component draws Apple Reminders-style lists and applies edits straight
away; the ops it sends are saved here with store.py and acknowledged in
`acked`, the same pattern as the timetable grid.
"""

from pathlib import Path

import streamlit as st

from venato import store

HERE = Path(__file__).parent

HOME_LIMIT = 6        # to-dos shown per card before "N more"

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
            # Added while Home is filtered to a category: it goes in that category.
            group = st.session_state.get("home_td_filter")
            details = {"group_id": group} if group and group != "all" else {}
            store.add_todo(t["title"], t["period"], t["period_start"], todo_id=t["id"],   # idempotent per id
                           repeat=t["period"] in store.REPEAT_BY_DEFAULT, **details)
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


def _on_ops():
    """Save new ops and remember them as acknowledged."""
    ops = st.session_state["home_todos"]["ops"] or []
    acked = st.session_state.setdefault("todo_acked", [])
    new_ops = [op for op in ops if op["opId"] not in acked]
    for op in new_ops:
        apply_op(op)
    # Keep the list short; a list only ever has a few ops in flight.
    st.session_state["todo_acked"] = (acked + [op["opId"] for op in new_ops])[-500:]


def render_home():
    """
    Today's and this week's to-dos, side by side (stacked when narrow), with the user's to-do
    categories as filters above, "Add" (the To-dos page's pop-up) and "See all".
    """
    from venato.ui import todo_page
    store.roll_todos()
    today = store.local_today()
    groups = {g["id"]: g for g in store.todo_groups()}
    with st.container(horizontal=True, vertical_alignment="center"):
        st.markdown("**To-dos**", width="stretch")
        add = st.button("Add", key="home_td_add", icon=":material/add:", type="tertiary",
                        help="New to-do with a date, category and how long it takes")
        st.button("See all", key="home_td_all", type="tertiary", on_click=todo_page.go_to_page)
    chosen = todo_page.filter_pills(groups, "home_td_filter")     # its own row, so the pills can wrap
    if add:
        todo_page.add_dialog(chosen)
    sections = []
    for period in store.HOME_TODO_PERIODS:
        start = store.start_of_period(period, today)
        todos = [t for t in store.todos_for(period, start) if chosen is None or t["group_id"] == chosen]
        sections.append({"period": period, "start": start.isoformat(),
                         "title": store.period_title(period, start, today),
                         "goals": todos, "limit": HOME_LIMIT})
    data = {"today": today.isoformat(), "sections": sections, "acked": st.session_state.get("todo_acked", [])}
    _todos_component(data=data, key="home_todos", on_ops_change=_on_ops)
