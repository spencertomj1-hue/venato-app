"""
Applications: a table of everything you've applied for (or mean to): industry, company,
route, description, contact / lead, deadline, status and notes.

"Add application" adds one. Click a cell in the table to change it; text too long for its
column ends in "…", which shows all of it in a bubble. Status is a coloured pill. Deletes can be undone.
"""

from pathlib import Path

import pandas as pd
import streamlit as st

from venato import regional
from venato import store
from venato import undo

HERE = Path(__file__).parent
PAGE = "Applications"
EDITOR = "apps_table"
ACKED = "apps_acked"        # ops from the table already saved
COLUMNS = {                 # store field -> column heading
    "industry": "Industry", "company": "Company", "route": "Route", "description": "Description",
    "contact": "Contact / lead", "deadline": "Deadline", "status": "Status", "notes": "Notes",
}
FIELD = {v: k for k, v in COLUMNS.items()}
DONE = {"Accepted", "Rejected", "Withdrawn"}          # finished: no countdown
COLOURS = {                 # status -> its pill's colour
    "To apply": "#9E9E9E", "Applied": "#1E88E5", "Online test": "#8E24AA", "Interview": "#FB8C00",
    "Assessment centre": "#00897B", "Offer": "#43A047", "Accepted": "#1B5E20", "Rejected": "#E53935",
    "Withdrawn": "#616161",
}

_table = st.components.v2.component(
    "venato_applications",
    html='<div class="ap-root"></div>',
    css=(HERE / "components" / "apps_component.css").read_text(encoding="utf-8"),
    js=(HERE / "components" / "apps_component.js").read_text(encoding="utf-8"),
)


def apply_op(op):
    """Save one op from the table: {kind: "edit", id, field, value} or {kind: "delete", id}."""
    a = store.get_application(op.get("id"))
    if not a:
        return
    if op["kind"] == "delete":
        undo.checkpoint(f"Deleted {a['company'] or 'an application'}")
        store.delete_application(a["id"])
    elif op["kind"] == "edit" and op.get("field") in COLUMNS:
        field, value = op["field"], op.get("value")
        if field == "status" and value not in store.APP_STATUSES:
            return
        if a[field] and (value or None) != a[field]:
            undo.checkpoint(f"Changed {a['company'] or 'an application'}", quiet=True)   # Cmd/Ctrl+Z puts it back
        store.update_application(a["id"], **{field: value})


def _on_ops():
    ops = (st.session_state.get(EDITOR) or {}).get("ops") or []
    acked = st.session_state.setdefault(ACKED, [])
    for op in ops:
        if op["opId"] not in acked:
            try:
                apply_op(op)
            except ValueError as e:
                st.toast(str(e), icon=":material/error:")
            acked.append(op["opId"])
    st.session_state[ACKED] = acked[-500:]


def _countdown(row, today):
    if not row["deadline"] or row["status"] in DONE:
        return ""
    return store.countdown(row["deadline"], today)


def _add_form():
    with st.expander("Add application", icon=":material/add:", expanded=not store.applications()):
        with st.form("apps_new", clear_on_submit=True, border=False):
            a, b, c = st.columns(3)
            company = a.text_input("Company")
            industry = b.text_input("Industry")
            route = c.text_input("Route", placeholder="e.g. Graduate scheme, Internship")
            a, b, c = st.columns(3)
            contact = a.text_input("Contact / lead")
            deadline = b.date_input("Deadline", value=None, format=regional.input_format())
            status = c.selectbox("Status", store.APP_STATUSES)
            description = st.text_input("Description")
            notes = st.text_area("Notes", height=80)
            if st.form_submit_button("Add", type="primary"):
                try:
                    store.add_application(company=company, industry=industry, route=route, contact=contact,
                                          deadline=deadline, status=status, description=description, notes=notes)
                except ValueError as e:
                    st.error(str(e))


def render_page():
    st.title("Applications")
    _add_form()                       # first, so a new one is in the table drawn below
    rows = store.applications()
    today = store.local_today()

    if rows:
        counts = pd.Series([r["status"] for r in rows]).value_counts()
        live = sum(n for s, n in counts.items() if s not in DONE and s != "To apply")
        st.caption(f"{len(rows)} in total · {live} in progress · "
                   + " · ".join(f"{n} {s.lower()}" for s, n in counts.items()))
    shown = st.pills("Show", store.APP_STATUSES, selection_mode="multi", key="apps_filter",
                     label_visibility="collapsed")
    if shown:
        rows = [r for r in rows if r["status"] in shown]

    _table(data={
        "rows": [{**{k: r[k] for k in COLUMNS}, "id": r["id"], "due": _countdown(r, today),
                  "deadlineText": regional.numeric_date(r["deadline"]) if r["deadline"] else ""} for r in rows],
        "statuses": store.APP_STATUSES, "colours": COLOURS, "acked": st.session_state.get(ACKED, []),
    }, key=EDITOR, on_ops_change=_on_ops)
    if not rows:
        st.caption("Nothing here yet: add one above." if not shown else "None with that status.")
    else:
        st.caption("Click a cell to change it · click … to read the rest · the bin at the end of a row deletes it "
                   "(Undo brings it back).")
