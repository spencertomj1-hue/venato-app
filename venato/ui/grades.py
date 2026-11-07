"""The Grades page (overall mark, a card per module with its assessments, settings) and its
Home widget. The data and maths are in venato/blocks/grades.py."""

import pandas as pd
import streamlit as st

from venato import store
from venato import undo
from venato.blocks import grades as gr


COLUMN_FIELD = {"Assessment": "name", "Weight %": "weight", "Mark %": "mark", "Due": "due"}


def _apply(key, ids):
    """Save the assessments table's edits and deletions."""
    state = st.session_state.get(key) or {}
    try:
        for i in state.get("deleted_rows", []):
            if int(i) < len(ids):
                gr.delete_assessment(ids[int(i)])
        for i, changes in state.get("edited_rows", {}).items():
            if int(i) < len(ids):
                gr.update_assessment(ids[int(i)], **{COLUMN_FIELD[c]: v for c, v in changes.items() if c in COLUMN_FIELD})
    except gr.GradeError as e:
        st.toast(str(e), icon=":material/error:")


def _module_card(m):
    n = gr.module_numbers(m)
    title = f"**{m['name']}**" + (f" · {m['code']}" if m["code"] else "") + f" · {m['credits']:g} credits" \
            + (f" · {m['year']}" if m["year"] else "")
    with st.expander(f"{title} · {gr.describe(n['projected'])}", expanded=False):
        a, b, c = st.columns(3)
        a.metric("Average so far", "–" if n["average"] is None else f"{n['average']:.1f}%")
        b.metric("Secured", f"{n['secured']:.1f}%", help="Marks already banked, out of the whole module")
        if n["needed"] is not None:
            label = {"reached": "Target reached", "impossible": "Target out of reach"}.get(n["status"])
            c.metric(f"Needed for {m['target']:g}%", label or f"{n['needed']:.0f}%",
                     help=f"Average needed on the remaining {n['left']:g}% of the module")
        else:
            c.metric("Marked", f"{n['done_weight']:g}%")
        st.progress(min(1.0, n["done_weight"] / 100), text=f"{n['done_weight']:g}% of the module marked"
                    + (f" · {n['planned_weight']:g}% of assessments added" if n["planned_weight"] < 100 else ""))
        rows = gr.assessments(m["id"])
        if rows:
            df = pd.DataFrame([{"Assessment": a["name"], "Weight %": a["weight"], "Mark %": a["mark"],
                                "Due": None if not a["due"] else store._as_date(a["due"])} for a in rows])
            key = f"gr_tbl_{m['id']}"
            st.data_editor(df, key=key, on_change=_apply, args=(key, [a["id"] for a in rows]), num_rows="delete",
                           hide_index=True, width="stretch",
                           column_config={"Weight %": st.column_config.NumberColumn(min_value=0, max_value=100),
                                          "Mark %": st.column_config.NumberColumn(min_value=0, max_value=100),
                                          "Due": st.column_config.DateColumn()})
        with st.form(f"gr_add_{m['id']}", clear_on_submit=True, border=False):
            x, y, z, w = st.columns([3, 1, 1, 2], vertical_alignment="bottom")
            name = x.text_input("New assessment", placeholder="e.g. Coursework 1")
            weight = y.number_input("Weight %", 0.0, 100.0, None)
            mark = z.number_input("Mark %", 0.0, 100.0, None)
            due = w.date_input("Due", None)
            if st.form_submit_button("Add assessment"):
                try:
                    gr.add_assessment(m["id"], name, weight, mark, due)
                    st.rerun()
                except gr.GradeError as e:
                    st.error(str(e))
        x, y, z, w = st.columns(4)
        target = x.number_input("Target %", 0.0, 100.0, m["target"], key=f"gr_t_{m['id']}")
        final = y.number_input("Final mark % (once known)", 0.0, 100.0, m["final"], key=f"gr_f_{m['id']}")
        credits = z.number_input("Credits", 1.0, 200.0, float(m["credits"]), key=f"gr_c_{m['id']}")
        year = w.text_input("Year", m["year"] or "", key=f"gr_y_{m['id']}")
        new = {"target": target, "final": final, "credits": credits, "year": year.strip() or None}
        if any(new[k] != m[k] for k in new):
            gr.update_module(m["id"], **new)
            st.rerun()
        if st.button("Delete module", key=f"gr_del_{m['id']}", icon=":material/delete:"):
            undo.checkpoint(f"Deleted the module {m['name']}")
            gr.delete_module(m["id"])
            st.rerun()


def render_page():
    st.title("Grades")
    ms = gr.modules()
    o = gr.overall()
    s = gr.settings()
    a, b, c = st.columns(3)
    a.metric("Overall (projected)", "–" if o["degree"] is None else f"{o['degree']:.1f}%")
    if s["system"] == "UK":
        b.metric("Classification", gr.classification(o["degree"]) or "–")
    elif s["system"] == "US":
        b.metric("GPA", "–" if o["gpa"] is None else f"{o['gpa']:.2f}")
    c.metric("Credits", f"{sum(m['credits'] for m in ms):g}")
    if len(o["years"]) > 1:
        st.caption(" · ".join(f"{y}: {v:.1f}%" for y, v in o["years"].items()))
    for m in ms:
        _module_card(m)
    with st.expander("Add a module", icon=":material/add:", expanded=not ms):
        with st.form("gr_new", clear_on_submit=True, border=False):
            x, y, z, w, v = st.columns([3, 1, 1, 2, 1])
            name = x.text_input("Module")
            code = y.text_input("Code")
            credits = z.number_input("Credits", 1.0, 200.0, 15.0)
            year = w.text_input("Year", placeholder="e.g. Year 2")
            target = v.number_input("Target %", 0.0, 100.0, None)
            if st.form_submit_button("Add module"):
                try:
                    gr.add_module(name, credits, year.strip() or None, target, code.strip() or None)
                    st.rerun()
                except gr.GradeError as e:
                    st.error(str(e))
    with st.expander("Settings", icon=":material/tune:"):
        system = st.segmented_control("Show grades as", list(gr.SYSTEMS), default=s["system"], key="gr_sys",
                                      help="UK: percentage and classification. US: letter grade and 4.0 GPA.")
        years = sorted({m["year"] for m in ms if m["year"]})
        weights = {}
        if years:
            st.caption("How much each year counts towards the overall mark (e.g. Year 2: 1, Year 3: 2)")
            cols = st.columns(min(4, len(years)))
            for i, y in enumerate(years):
                weights[y] = cols[i % len(cols)].number_input(y, 0.0, 10.0, float(s["years"].get(y, 1)),
                                                              0.5, key=f"gr_yw_{y}")
        if (system or s["system"]) != s["system"] or any(weights[y] != float(s["years"].get(y, 1)) for y in weights):
            gr.save_settings(system or s["system"], weights)
            st.rerun()


def render_home():
    st.markdown("**Grades**")
    o = gr.overall()
    if o["degree"] is None:
        st.caption("No marks yet.")
        return
    text = gr.describe(o["degree"], o["gpa"])
    due = sorted((a["due"], a["name"], m["name"]) for m in gr.modules() for a in gr.assessments(m["id"])
                 if a["due"] and a["mark"] is None and a["due"] >= store.local_today().isoformat())
    if due:
        text += f" · next: {due[0][2]} {due[0][1]} ({store.fmt_day(store._as_date(due[0][0]), '%-d %b')})"
    st.caption(text)
