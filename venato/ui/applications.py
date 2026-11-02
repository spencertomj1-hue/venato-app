"""
Applications: a table of everything you've applied for (or mean to): industry, company,
route, description, contact / lead, deadline, status and notes.

"Add application" adds one. Then edit the table like a spreadsheet: click a cell to change
it, tick rows and press the bin (or Delete) to remove them. Deletes can be undone.
"""

import pandas as pd
import streamlit as st

from venato import regional
from venato import store
from venato import undo

PAGE = "Applications"
EDITOR = "apps_editor"
IDS = "apps_ids"            # the id behind each row of the table as it was last drawn
COLUMNS = {                 # store field -> column heading
    "industry": "Industry", "company": "Company", "route": "Route", "description": "Description",
    "contact": "Contact / lead", "deadline": "Deadline", "status": "Status", "notes": "Notes",
}
FIELD = {v: k for k, v in COLUMNS.items()}
DONE = {"Accepted", "Rejected", "Withdrawn"}          # finished: no countdown


def apply_edits(state, ids):
    """Save st.data_editor's changes ({edited_rows, deleted_rows}, rows numbered as in `ids`).
    Streamlit starts the count again whenever the table it's given changes, which it does
    after every save, so each call only holds the latest change."""
    gone = [ids[int(i)] for i in state.get("deleted_rows", []) if int(i) < len(ids)]
    gone = [a for a in gone if store.get_application(a)]
    if gone:
        names = [store.get_application(a)["company"] or "application" for a in gone]
        undo.checkpoint(f"Deleted {names[0]}" if len(gone) == 1 else f"Deleted {len(gone)} applications")
    elif state.get("edited_rows"):
        undo.checkpoint("Changed an application", quiet=True)
    for aid in gone:
        store.delete_application(aid)
    for i, changes in state.get("edited_rows", {}).items():
        aid = ids[int(i)] if int(i) < len(ids) else None
        if aid and aid not in gone and store.get_application(aid):
            fields = {FIELD[k]: v for k, v in changes.items() if k in FIELD}
            if "status" in fields and not fields["status"]:
                fields["status"] = "To apply"
            store.update_application(aid, **fields)


def _save():
    try:
        apply_edits(st.session_state.get(EDITOR) or {}, st.session_state.get(IDS) or [])
    except ValueError as e:
        st.toast(str(e), icon=":material/error:")


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

    st.session_state[IDS] = [r["id"] for r in rows]
    table = pd.DataFrame(
        [{**{COLUMNS[k]: r[k] for k in COLUMNS}, "Due": _countdown(r, today)} for r in rows],
        columns=[*COLUMNS.values(), "Due"])
    table["Deadline"] = pd.to_datetime(table["Deadline"]).dt.date
    text = [c for c in table.columns if c not in ("Deadline", "Status")]
    table[text] = table[text].fillna("")              # blank, not "None"

    st.data_editor(
        table, key=EDITOR, on_change=_save, num_rows="delete", hide_index=True, width="stretch",
        column_order=["Industry", "Company", "Route", "Description", "Contact / lead",
                      "Deadline", "Due", "Status", "Notes"],
        column_config={
            "Industry": st.column_config.TextColumn(width=90),
            "Company": st.column_config.TextColumn(width=130),
            "Route": st.column_config.TextColumn(width=110, help="e.g. Graduate scheme, Internship, Spring week"),
            "Description": st.column_config.TextColumn(width=150),
            "Contact / lead": st.column_config.TextColumn(width=120, help="Who you know there, or who to ask"),
            "Deadline": st.column_config.DateColumn(format=regional.date_format(), width=100),
            "Due": st.column_config.TextColumn(disabled=True, width=90),
            "Status": st.column_config.SelectboxColumn(options=store.APP_STATUSES, required=True, width=120),
            "Notes": st.column_config.TextColumn(width=150),
        },
    )
    if table.empty:
        st.caption("Nothing here yet: add one above." if not shown else "None with that status.")
    else:
        st.caption("Click a cell to change it · tick rows and press the bin to delete them (Undo brings them back).")
