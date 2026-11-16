"""
The To-dos page.

Each to-do has a due day, one of the user's own to-do categories (e.g. "At home repairs",
made here, separate from the timetable's) and how long it should take. To-dos don't go on the
timetable. Lists are sorted by urgency (due day).
"Add new to-do" opens a pop-up. Home keeps the compact cards (todos.py), with category filters.
SQL lives in store.py.
"""

from datetime import timedelta
from html import escape

import streamlit as st

from venato import store

PAGE = "To-dos"                          # sidebar label (also what Home's "See all" switches to)
LENGTHS = {"15 min": 15, "30 min": 30, "45 min": 45, "1 hour": 60, "1½ hours": 90, "2 hours": 120,
           "3 hours": 180, "4 hours": 240}
NONE = "No category"
NEW = "+ New category…"


def go_to_page():
    st.session_state["page"] = PAGE      # the sidebar radio's key; button callbacks run before it's drawn


def _length_name(minutes):
    minutes = minutes or store.TODO_MINUTES
    return next((k for k, v in LENGTHS.items() if v == minutes), f"{minutes} min")


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


def _section(due, today):
    days = (due - today).days
    if days < 0:
        return "Overdue"
    if days <= 1:
        return ("Today", "Tomorrow")[days]
    return "This week" if due <= today + timedelta(days=6 - today.weekday()) else "Later"


STYLE = """<style>
  .td-meta { font-size: 0.78rem; opacity: 0.75; margin: -14px 0 4px 28px; display: flex; flex-wrap: wrap;
             gap: 2px 5px; align-items: center; }
  .td-due.late { color: #EF4444; font-weight: 600; }
  .td-chip { padding: 0 7px; border-radius: 999px; color: #111; font-weight: 600; }
</style>"""


def _meta(t, today, groups):
    due = store.todo_due(t)
    bits = [f'<span class="td-due{" late" if due < today else ""}">{escape(_due_name(due, today))}</span>']
    g = groups.get(t["group_id"])
    if g:
        bits.append(f'<span class="td-chip" style="background:{escape(g["colour"])}">{escape(g["name"])}</span>')
    bits.append(_length_name(t["minutes"]))
    return '<div class="td-meta">' + " · ".join(bits) + "</div>"


def _tick(todo_id, key):
    store.set_todo_done(todo_id, st.session_state[key])


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


@st.dialog("New to-do")
def add_dialog(group_id=None):
    """The pop-up behind 'Add new to-do' (Home's category filter, if any, is the default)."""
    groups = {g["id"]: g for g in store.todo_groups()}
    title = st.text_input("What needs doing?", key="tdn_title")
    a, b = st.columns(2)
    due = a.date_input("Done by", store.local_today(), key="tdn_due", format="DD/MM/YYYY")
    length = b.selectbox("How long will it take?", list(LENGTHS), index=1, key="tdn_len")
    picked, new_name = _group_picker("Category", groups, group_id, "tdn_group")
    if st.button("Add to-do", type="primary", icon=":material/add:", key="tdn_add"):
        if not title.strip():
            st.error("Give the to-do a name.")
            return
        store.add_detailed_todo(title, due=due, group_id=_resolve_group(picked, new_name),
                                minutes=LENGTHS[length])
        st.rerun()


def _edit(t, groups):
    k = f"tde_{t['id']}_{t['due']}_{t['group_id']}_{t['minutes']}_{t['in_diary']}"
    title = st.text_input("To-do", t["title"], key=f"{k}_t")
    due = st.date_input("Done by", store.todo_due(t), key=f"{k}_d", format="DD/MM/YYYY")
    picked, new_name = _group_picker("Category", groups, t["group_id"], f"{k}_g")
    name = _length_name(t["minutes"])
    length = st.selectbox("How long", list(LENGTHS), key=f"{k}_l",
                          index=list(LENGTHS).index(name) if name in LENGTHS else 1)
    notes = st.text_area("Notes", t["notes"] or "", key=f"{k}_n", height=68)
    save, delete = st.columns(2)
    if save.button("Save", key=f"{k}_s", type="primary", icon=":material/check:", width="stretch"):
        if not title.strip():
            st.error("A to-do needs a name.")
            return
        store.update_todo(t["id"], title=title, notes=notes, due=due, group_id=_resolve_group(picked, new_name),
                          minutes=LENGTHS[length])
        st.rerun()
    if delete.button("Delete", key=f"{k}_x", icon=":material/delete:", width="stretch"):
        store.delete_todo(t["id"])
        st.rerun()


def _row(t, today, groups, prefix, editable=True):
    key = f"{prefix}_{t['id']}"
    st.session_state[key] = t["done"]
    tick, more = st.columns([14, 1], vertical_alignment="top")
    tick.checkbox(t["title"], key=key, on_change=_tick, args=(t["id"], key), help=t["notes"])
    tick.html(_meta(t, today, groups))
    if editable:
        with more.popover("", icon=":material/more_horiz:", help="Change or delete it"):
            _edit(t, groups)


def _manage_groups(groups):
    with st.popover("Categories", icon=":material/label:"):
        st.caption("Your own to-do categories. Deleting one keeps its to-dos, with no category.")
        for g in groups.values():
            name, colour, delete = st.columns([5, 1, 1], vertical_alignment="bottom")
            new = name.text_input("Name", g["name"], key=f"tdg_n_{g['id']}", label_visibility="collapsed")
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


def filter_pills(groups, key):
    """'All' plus one pill per to-do category; returns the chosen group id, or None for all."""
    if not groups:
        return None
    names = {g["id"]: g["name"] for g in groups.values()}
    choice = st.pills("Filter", ["all", *names], default="all", key=key, label_visibility="collapsed",
                      format_func=lambda i: "All" if i == "all" else names[i])
    return None if choice in (None, "all") else choice


def render_page():
    st.header("To-dos")
    store.roll_todos()
    today = store.local_today()
    groups = {g["id"]: g for g in store.todo_groups()}
    st.html(STYLE)
    with st.container(horizontal=True):
        add = st.button("Add new to-do", type="primary", icon=":material/add:", key="td_new")
        _manage_groups(groups)
    chosen = filter_pills(groups, "td_filter")
    if add:
        add_dialog(chosen)                 # filtered to a category: the new to-do goes in it

    todos = [t for t in store.all_open_todos(today) if chosen is None or t["group_id"] == chosen]
    if not todos:
        st.caption("Nothing to do here.")
    sections = {}
    for t in todos:
        sections.setdefault(_section(store.todo_due(t), today), []).append(t)
    for name in ("Overdue", "Today", "Tomorrow", "This week", "Later"):
        if name in sections:
            hours = sum((t["minutes"] or store.TODO_MINUTES) for t in sections[name]) / 60
            st.markdown(f"**{name}** :gray[· {len(sections[name])} · {hours:g} h]")
            for t in sections[name]:
                _row(t, today, groups, "td")

    done = [t for t in store.done_todos(today) if chosen is None or t["group_id"] == chosen]
    if done:
        with st.expander(f"Done this week ({len(done)})"):
            for t in done:
                _row(t, today, groups, "tdd", editable=False)
