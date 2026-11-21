"""
The Home page's to-do lists: today's, this week's and this month's, in one
card with a Daily / Weekly / Monthly switch (one list at a time). This is the Python side of the to-do list component
(todos_component.js/.css).

The component draws Apple Reminders-style lists and applies edits straight
away; the ops it sends are saved here with the store and acknowledged in
`acked`, the same pattern as the timetable grid.

Each to-do can also have a due day, how long it takes and one of the user's own to-do categories
(store.todo_groups; every goal is one too, e.g. "Get a job"). Rows show them; the row menu's "Due day,
category, length…" and the page's "Add to-do" open pop-ups for them. The page's category filter applies
to every tab; "By due date" lists every open to-do by when it's due and "By category" under its category.
"""

from datetime import timedelta
from pathlib import Path

import streamlit as st

from venato import regional, store
from venato.ui import kit

HERE = Path(__file__).parent

HOME_LIMIT = 3        # to-dos Home's tile shows before "+N more"

_todos_component = st.components.v2.component(
    "venato_todos",
    html='<div class="gl-root"></div>',
    css=(HERE / "components" / "todos_component.css").read_text(encoding="utf-8"),
    js=(HERE / "components" / "todos_component.js").read_text(encoding="utf-8"),
)


def apply_op(op):
    """
    Save one op from a to-do list:
      {kind: "add", goal: {id, title, period, period_start, group_id?}}
      {kind: "toggle", id, done}        {kind: "edit", id, title | notes}
      {kind: "repeat", id, repeat}      {kind: "move", id, period}
      {kind: "delete", id}              {kind: "reorder", ids}
    """
    kind = op["kind"]
    if kind == "add":
        t = op["goal"]
        if t["title"].strip():
            group = {"group_id": t["group_id"]} if t.get("group_id") else {}   # from a list filtered to a category
            store.add_todo(t["title"], t["period"], t["period_start"], todo_id=t["id"], **group)   # idempotent per id
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
    elif kind == "details":
        st.session_state["todo_details"] = op["id"]     # the next full run opens its pop-up


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
    if any(op["kind"] == "details" for op in new_ops):
        st.rerun(scope="app")                            # a pop-up opens from the full app run
    kit.rerun_app_if(set().union(*(_changed(op) for op in new_ops)))


@st.fragment
def render_home():
    """Today's, this week's and this month's to-dos: one card, its header switching between the lists
    (the tile header names it; the component draws the switch and starts on the first list with open to-dos)."""
    store.roll_todos()
    today = store.local_today()
    _details_from_menu()
    groups = _groups()
    sections = []
    for period in store.TODO_PERIODS:
        start = store.start_of_period(period, today)
        sections.append({"period": period, "start": start.isoformat(),
                         "title": store.period_title(period, start, today),
                         "goals": _with_meta(store.todos_for(period, start), today, groups), "limit": HOME_LIMIT})
    with st.container(border=True, key="home_todos_card"):
        data = {"today": today.isoformat(), "sections": sections, "tile": True,
                "acked": st.session_state.get("todo_acked", [])}
        _todos_component(data=data, key="home_todos", on_ops_change=_on_ops)


# ---------------------------------------------------------------------------
# The To-dos page (Home's To-dos tile opens it): one list at a time, Today / This week / This month
# ---------------------------------------------------------------------------

TABS = {"Today": "daily", "This week": "weekly", "This month": "monthly", "By due date": "due",
        "By category": "category"}
VIEWS = ("due", "category")      # the tabs that aren't one list


def _section(period, today, limit=None, group_id=None):
    """One list for the component; with group_id, only that category's to-dos."""
    start = store.start_of_period(period, today)
    todos = [t for t in store.todos_for(period, start) if group_id is None or t["group_id"] == group_id]
    return {"period": period, "start": start.isoformat(), "title": store.period_title(period, start, today),
            "goals": _with_meta(todos, today, _groups()), "limit": limit}


def _page_ops(key, group_id):
    """A list filtered to one category: what's added there goes in that category (or it would vanish)."""
    if group_id:
        for op in st.session_state[key]["ops"] or []:
            if op["kind"] == "add":
                op["goal"].setdefault("group_id", group_id)
    _on_ops(key)


@st.fragment
def _page_list(period, group_id=None):
    today = store.local_today()
    key = f"page_todos_{period}" + (f"_{group_id}" if group_id else "")
    with st.container(border=True, key="todos_page_card"):
        data = {"today": today.isoformat(), "sections": [_section(period, today, group_id=group_id)],
                "single": True, "acked": st.session_state.get("todo_acked", [])}
        _todos_component(data=data, key=key, on_ops_change=lambda: _page_ops(key, group_id))


def _filter(groups):
    """The page's category filter (every tab): the chosen category's id, or None for all."""
    if not groups:
        return None
    names = {g["id"]: g["name"] for g in groups.values()}
    if st.session_state.get("td_filter") not in (None, "all", *names):
        st.session_state["td_filter"] = "all"                # its category was deleted
    pick = st.pills("Category", ["all", *names], default="all", key="td_filter", label_visibility="collapsed",
                    format_func=lambda i: "All" if i == "all" else names[i])
    return None if pick in (None, "all") else pick


def render_page():
    store.roll_todos()
    today = store.local_today()
    _details_from_menu()
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
    groups = _groups()
    with st.container(horizontal=True, key="todos_tools"):
        add = st.button("Add to-do", type="primary", icon=":material/add:", key="td_new")
        _manage_groups(groups)
    chosen = _filter(groups)
    if add:
        add_dialog(chosen, None if period in VIEWS else period)
    main, side = st.columns([2, 1], gap="medium")
    with main:
        if period == "due":
            _due_view(today, groups, chosen)
        elif period == "category":
            _category_view(today, groups, chosen)
        else:
            _page_list(period, chosen)
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


# ---------------------------------------------------------------------------
# Due days, how long, and the user's own to-do categories
# ---------------------------------------------------------------------------

LENGTHS = {"15 min": 15, "30 min": 30, "45 min": 45, "1 hour": 60, "1½ hours": 90, "2 hours": 120,
           "3 hours": 180, "4 hours": 240}
NO_LENGTH = "Not set"
NONE = "No category"
NEW = "+ New category…"
WHEN = ("Overdue", "Today", "Tomorrow", "This week", "Later")


def _groups():
    return {g["id"]: g for g in store.todo_groups()}


def _length_name(minutes):
    return next((k for k, v in LENGTHS.items() if v == minutes), f"{minutes} min") if minutes else None


def _due_name(due, today):
    days = (due - today).days
    if days < -1:
        return f"Overdue ({due.day} {due:%b})"
    if days == -1:
        return "Overdue (yesterday)"
    if days == 0:
        return "Today"
    if days == 1:
        return "Tomorrow"
    return f"{due:%a}" if days < 7 else f"{due:%a} {due.day} {due:%b}"


def _with_meta(todos, today, groups):
    """The to-dos with `meta` for the list's rows: due day (in words), category and length, when set."""
    for t in todos:
        due = store._as_date(t["due"]) if t.get("due") else None
        g = groups.get(t.get("group_id"))
        t["meta"] = {"due": _due_name(due, today) if due else None,
                     "late": bool(due and due < today and not t["done"]),
                     "group": {"name": g["name"], "colour": g["colour"]} if g else None,
                     "length": _length_name(t.get("minutes"))}
    return todos


def _when(due, today):
    days = (due - today).days
    if days < 0:
        return "Overdue"
    if days <= 1:
        return ("Today", "Tomorrow")[days]
    return "This week" if due <= today + timedelta(days=6 - today.weekday()) else "Later"


def _group_picker(label, groups, current, key):
    """A category select with '+ New category…' at the end; returns (group_id or None, new name or None)."""
    options = [NONE, *groups, NEW]
    choice = st.selectbox(label, options, key=key, index=options.index(current) if current in groups else 0,
                          format_func=lambda o: groups[o]["name"] if o in groups else o)
    if choice == NEW:
        return None, st.text_input("New category name", key=f"{key}_new", placeholder="e.g. At home repairs")
    return (choice if choice in groups else None), None


def _resolve_group(group_id, new_name):
    if new_name and new_name.strip():
        return store.add_todo_group(new_name)["id"]
    return group_id


def _length_picker(key, minutes=None):
    options = [NO_LENGTH, *LENGTHS]
    name = _length_name(minutes)
    choice = st.selectbox("How long will it take?", options, key=key,
                          index=options.index(name) if name in LENGTHS else 0)
    return LENGTHS.get(choice)


@st.dialog("New to-do")
def add_dialog(group_id=None, period=None):
    """'Add to-do': a title, a due day (it goes in the list that day falls in), a category and a length.
    With no due day it goes in the list on screen (today's, from By due date)."""
    groups = _groups()
    title = st.text_input("What needs doing?", key="tdn_title")
    a, b = st.columns(2)
    due = a.date_input("Done by", None, key="tdn_due", format=regional.input_format(),
                       help="Leave it empty for no due day.")
    with b:
        minutes = _length_picker("tdn_len")
    picked, new_name = _group_picker("Category", groups, group_id, "tdn_group")
    if st.button("Add to-do", type="primary", icon=":material/add:", key="tdn_add"):
        if not title.strip():
            st.error("Give the to-do a name.")
            return
        group = _resolve_group(picked, new_name)
        if due or not period:
            store.add_detailed_todo(title, due=due, group_id=group, minutes=minutes)
        else:
            store.add_todo(title, period, store.local_today(), group_id=group, minutes=minutes)
        st.rerun()


@st.dialog("Due day, category, length")
def details_dialog(todo_id):
    """The row menu's pop-up: change a to-do's due day, category and length (a new due day moves it to
    the list that day falls in)."""
    t = store.get_todo(todo_id)
    if not t:
        st.caption("That to-do has gone.")
        return
    groups = _groups()
    st.markdown(f"**{kit.md(t['title'])}**")
    k = f"tdd_{t['id']}"
    due = st.date_input("Done by", store._as_date(t["due"]) if t["due"] else None, key=f"{k}_d",
                        format=regional.input_format(), help="Leave it empty for no due day.")
    picked, new_name = _group_picker("Category", groups, t["group_id"], f"{k}_g")
    minutes = _length_picker(f"{k}_l", t["minutes"])
    if st.button("Save", key=f"{k}_s", type="primary", icon=":material/check:"):
        store.update_todo(t["id"], due=due, group_id=_resolve_group(picked, new_name), minutes=minutes)
        st.rerun()


def _details_from_menu():
    todo_id = st.session_state.pop("todo_details", None)
    if todo_id:
        details_dialog(todo_id)


def _manage_groups(groups):
    with st.popover("Categories", icon=":material/label:"):
        st.caption("Your own to-do categories (separate from the timetable's). Each goal you set is one too "
                   ":material/flag:. Deleting one keeps its to-dos, with no category.")
        for g in groups.values():
            name, colour, delete = st.columns([5, 1, 1], vertical_alignment="bottom")
            new = name.text_input("Name", g["name"], key=f"tdg_n_{g['id']}", label_visibility="collapsed",
                                  icon=":material/flag:" if g["goal_id"] else None,
                                  help="From your goal of that name" if g["goal_id"] else None)
            col = colour.color_picker("Colour", g["colour"], key=f"tdg_c_{g['id']}", label_visibility="collapsed")
            if new.strip() != g["name"] or col != g["colour"]:
                store.update_todo_group(g["id"], new, col)
                st.rerun()
            if delete.button("", key=f"tdg_x_{g['id']}", icon=":material/delete:", help=f"Delete {g['name']}"):
                store.delete_todo_group(g["id"])
                st.rerun()
        with st.form("tdg_add", clear_on_submit=True, border=False):
            name = st.text_input("New category", placeholder="e.g. At home repairs")
            if st.form_submit_button("Add category", icon=":material/add:") and name.strip():
                store.add_todo_group(name)
                st.rerun()


def _tick(todo_id, key):
    store.set_todo_done(todo_id, st.session_state[key])


def _meta_line(t, today, groups):
    m = _with_meta([dict(t)], today, groups)[0]["meta"]
    bits = [f":red[{m['due']}]" if m["late"] else m["due"] or "No due day"]
    if m["group"]:
        bits.append(f"**{kit.md(m['group']['name'])}**")
    if m["length"]:
        bits.append(m["length"])
    return " · ".join(bits)


def _row(t, today, groups, prefix, editable=True):
    key = f"{prefix}_{t['id']}"
    st.session_state[key] = t["done"]
    tick, more = st.columns([14, 1], vertical_alignment="top")
    tick.checkbox(t["title"], key=key, on_change=_tick, args=(t["id"], key), help=t["notes"])
    tick.caption(_meta_line(t, today, groups))
    if editable and more.button("", key=f"{key}_edit", icon=":material/more_horiz:",
                                help="Due day, category, length"):
        details_dialog(t["id"])


def _hours(rows):
    return f":gray[· {len(rows)} · about {sum(t['minutes'] or store.TODO_MINUTES for t in rows) / 60:g} h]"


def _category_view(today, groups, chosen=None):
    """Every open to-do (as By due date has them), under its category in the categories' order, most urgent
    first in each; "No category" last. A goal's category says so."""
    todos = [t for t in store.open_todos(today) if chosen is None or t["group_id"] == chosen]
    with st.container(border=True, key="todos_cat_card"):
        if not todos:
            st.caption("Nothing to do here.")
        by = {}
        for t in todos:
            by.setdefault(t["group_id"] if t["group_id"] in groups else None, []).append(t)
        for gid in [*groups, None]:
            if gid in by:
                g = groups.get(gid)
                name = f"**{kit.md(g['name'])}**" + (" :material/flag:" if g["goal_id"] else "") if g else \
                    "**No category**"
                st.markdown(f"{name} {_hours(by[gid])}")
                for t in by[gid]:
                    _row(t, today, groups, "tdc")


def _due_view(today, groups, chosen=None):
    """Every open to-do from today's, this week's and this month's lists (and later ones with a due day),
    most urgent first, in Overdue / Today / Tomorrow / This week / Later, in the chosen category (or all)."""
    todos = [t for t in store.open_todos(today) if chosen is None or t["group_id"] == chosen]
    with st.container(border=True, key="todos_due_card"):
        if not todos:
            st.caption("Nothing to do here.")
        sections = {}
        for t in todos:
            sections.setdefault(_when(store.todo_due(t), today), []).append(t)
        for name in WHEN:
            if name in sections:
                rows = sections[name]
                st.markdown(f"**{name}** {_hours(rows)}")
                for t in rows:
                    _row(t, today, groups, "td")
        done = [t for t in store.done_todos(today) if chosen is None or t["group_id"] == chosen]
        if done:
            with st.expander(f"Done in the last week ({len(done)})"):
                for t in done:
                    _row(t, today, groups, "tdd", editable=False)
