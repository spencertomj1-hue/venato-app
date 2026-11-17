"""The Grades page (where you stand overall, a chart of every module against the classification
bands, what's due next, and a card per module with its assessments) and its Home widget.
The data and maths are in venato/blocks/grades.py."""

from html import escape

import altair as alt
import pandas as pd
import streamlit as st

from venato import store
from venato import undo
from venato.blocks import grades as gr
from venato.ui import kit


COLUMN_FIELD = {"Assessment": "name", "Weight %": "weight", "Mark %": "mark", "Due": "due"}
OPEN = "gr_open"


def _band(pct):
    """(label, colour) for a mark: green at the top band, then blue, amber, orange, red."""
    if pct is None:
        return "–", "#BAB0AC"
    dark = kit.appearance.is_dark()
    tones = (["#4ADE80", "#60A5FA", "#FBBF24", "#FB923C", "#FF7B72"] if dark
             else ["#146C2E", "#1D5FB4", "#B45309", "#C2410C", "#C62828"])
    system = gr.settings()["system"]
    if system == "US":
        label = gr.letter(pct)[0]
        i = 0 if pct >= 90 else 1 if pct >= 80 else 2 if pct >= 70 else 3 if pct >= 60 else 4
    else:
        i = 0 if pct >= 70 else 1 if pct >= 60 else 2 if pct >= 50 else 3 if pct >= 40 else 4
        label = gr.classification(pct) if system == "UK" else f"{pct:.0f}%"
    return label, tones[i]


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


# --- Overview ---

def _stats(ms, o, s):
    numbers = [gr.module_numbers(m) for m in ms]
    weight = sum(m["credits"] for m in ms) or 1
    marked = sum(m["credits"] * n["done_weight"] for m, n in zip(ms, numbers)) / weight
    label, _ = _band(o["degree"])
    items = [{"label": "Overall (projected)", "value": "–" if o["degree"] is None else f"{o['degree']:.1f}%",
              "help": "Credit-weighted, with years weighted as set in Settings"}]
    if s["system"] == "UK":
        items.append({"label": "Classification", "value": gr.classification(o["degree"]) or "–"})
    elif s["system"] == "US":
        items.append({"label": "GPA", "value": "–" if o["gpa"] is None else f"{o['gpa']:.2f}"})
    items += [{"label": "Credits", "value": f"{sum(m['credits'] for m in ms):g}", "help": f"{len(ms)} modules"},
              {"label": "Marked so far", "value": f"{marked:.0f}%", "help": "Of all your modules, by credits"}]
    kit.stats(items)


def _chart(ms):
    rows = []
    for m in ms:
        n = gr.module_numbers(m)
        if n["projected"] is not None:
            rows.append((m, n))
    if not rows:
        kit.empty("Add some marks to see where each module stands.", ":material/bar_chart:")
        return
    rows.sort(key=lambda r: r[1]["projected"])
    names = [m["code"] or m["name"] for m, _ in rows]
    top = max(100, max(n["projected"] for _, n in rows))
    df = pd.DataFrame({"Module": names, "Projected": [n["projected"] for _, n in rows],
                       "Name": [m["name"] for m, _ in rows], "Band": [_band(n["projected"])[0] for _, n in rows],
                       "Marked": [n["done_weight"] for _, n in rows], "Colour": [_band(n["projected"])[1] for _, n in rows],
                       "Label": [f"{n['projected']:.0f}%" for _, n in rows]})
    x_enc = alt.X("Projected", type="quantitative", scale=alt.Scale(domain=[0, top], nice=False),
                  axis=alt.Axis(values=list(range(0, int(top) + 1, 10)), labelExpr="datum.value + '%'", title=None))
    y_enc = alt.Y("Module", type="nominal", sort=names[::-1], axis=alt.Axis(grid=False, title=None))
    bars = alt.Chart(df).mark_bar(size=24).encode(
        x=x_enc, y=y_enc, color=alt.Color("Colour", type="nominal", scale=None),
        tooltip=["Name", alt.Tooltip("Projected", format=".1f", title="Projected %"), "Band",
                 alt.Tooltip("Marked", format=".0f", title="Marked %")])
    ink = "#111318" if kit.appearance.is_dark() else "white"
    text = alt.Chart(df).mark_text(align="left", dx=6, color=ink, fontSize=12).encode(
        x=alt.value(0), y=y_enc, text="Label:N")
    layers = bars + text
    targets = pd.DataFrame([{"Module": names[i], "Target": m["target"]} for i, (m, _) in enumerate(rows)
                            if m["target"] is not None])
    if not targets.empty:
        layers += alt.Chart(targets).mark_tick(thickness=3, size=30, color="rgba(128,128,128,0.9)").encode(
            x=alt.X("Target", type="quantitative", scale=alt.Scale(domain=[0, top], nice=False)), y=y_enc,
            tooltip=[alt.Tooltip("Target", format=".0f", title="Target %")])
    lines = [40, 50, 60, 70] if gr.settings()["system"] != "US" else [60, 70, 80, 90]
    layers = alt.Chart(pd.DataFrame({"x": lines})).mark_rule(strokeDash=[2, 3], color="rgba(128,128,128,0.4)").encode(
        x=alt.X("x:Q", scale=alt.Scale(domain=[0, top], nice=False))) + layers
    kit.show(kit.style(layers, max(220, 46 * len(rows) + 40), legend=False), key="gr_chart")
    st.caption("Bars are each module's projected mark; the grey tick is its target; dotted lines are the grade "
               "boundaries.")


def _coming_up(ms):
    today = store.local_today().isoformat()
    due = sorted(((a["due"], a, m) for m in ms for a in gr.assessments(m["id"])
                  if a["due"] and a["mark"] is None and a["due"] >= today), key=lambda x: x[0])
    if not due:
        kit.empty("Nothing due. Add due dates to assessments to see them here.", ":material/event_available:")
        return
    for d, a, m in due[:6]:
        n = gr.module_numbers(m)
        need = ""
        if n["needed"] is not None and n["status"] == "possible":
            need = f"need {n['needed']:.0f}% on the rest for {m['target']:g}%"
        elif n["status"] == "reached":
            need = "target already reached"
        day = store._as_date(d)
        kit.html(f"<div style='display:flex;gap:12px;align-items:center;margin:2px 0 6px'>{kit.date_badge(day)}"
                 f"<div><b>{escape(a['name'])}</b> · {a['weight']:g}%<br>"
                 f"<span style='opacity:.7;font-size:.85rem'>{escape(m['name'])}"
                 f"{' · ' + need if need else ''}</span></div></div>")


# --- Modules ---

def _assessments(m):
    rows = gr.assessments(m["id"])
    if rows:
        df = pd.DataFrame([{"Assessment": a["name"], "Weight %": a["weight"], "Mark %": a["mark"],
                            "Due": None if not a["due"] else store._as_date(a["due"])} for a in rows])
        key = f"gr_tbl_{m['id']}"
        st.data_editor(df, key=key, on_change=_apply, args=(key, [a["id"] for a in rows]), num_rows="delete",
                       hide_index=True, width="stretch",
                       column_config={"Weight %": st.column_config.NumberColumn(min_value=0, max_value=100),
                                      "Mark %": st.column_config.NumberColumn(min_value=0, max_value=100),
                                      "Due": st.column_config.DateColumn(format="D MMM YYYY")})
    with st.form(f"gr_add_{m['id']}", clear_on_submit=True, border=False):
        x, y, z, w = st.columns([3, 1, 1, 2], vertical_alignment="bottom")
        name = x.text_input("New assessment", placeholder="e.g. Coursework 1")
        weight = y.number_input("Weight %", 0.0, 100.0, None)
        mark = z.number_input("Mark %", 0.0, 100.0, None)
        due = w.date_input("Due", None)
        if st.form_submit_button("Add assessment", icon=":material/add:"):
            try:
                gr.add_assessment(m["id"], name, weight, mark, due)
                st.rerun()
            except gr.GradeError as e:
                st.error(str(e))


def _module_settings(m):
    x, y, z, w = st.columns(4)
    target = x.number_input("Target %", 0.0, 100.0, m["target"], key=f"gr_t_{m['id']}")
    final = y.number_input("Final mark %", 0.0, 100.0, m["final"], key=f"gr_f_{m['id']}", help="Once it's known")
    credits = z.number_input("Credits", 1.0, 200.0, float(m["credits"]), key=f"gr_c_{m['id']}")
    year = w.text_input("Year", m["year"] or "", key=f"gr_y_{m['id']}")
    new = {"target": target, "final": final, "credits": credits, "year": year.strip() or None}
    if any(new[k] != m[k] for k in new):
        gr.update_module(m["id"], **new)
        st.rerun()
    with st.popover("Delete module", icon=":material/delete:"):
        st.warning(f"Delete {m['name']} and its assessments? (Undo can bring it back.)")
        if st.button("Delete", key=f"gr_del_{m['id']}", type="primary"):
            undo.checkpoint(f"Deleted the module {m['name']}")
            gr.delete_module(m["id"])
            st.rerun()


def _module_card(m):
    n = gr.module_numbers(m)
    label, colour = _band(n["projected"])
    with st.container(border=True, height="stretch"):
        left, right = st.columns([1, 2.4], vertical_alignment="center")
        with left:
            kit.rings([{"frac": (n["projected"] or 0) / 100, "colour": colour, "size": 96,
                        "centre": "–" if n["projected"] is None else f"{n['projected']:.0f}%",
                        "centre_sub": label if n["projected"] is not None else ""}])
        with right:
            st.markdown(f"**{escape(m['name'])}**")
            bits = [b for b in (m["code"], f"{m['credits']:g} credits", m["year"]) if b]
            st.caption(" · ".join(bits))
            if m["final"] is not None:
                line = f"Final mark {m['final']:g}%"
            elif n["needed"] is None:
                line = "No target set" if m["target"] is None else "All marked"
            elif n["status"] == "reached":
                line = f":green[Target {m['target']:g}% reached]"
            elif n["status"] == "impossible":
                line = f":red[Target {m['target']:g}% out of reach]"
            else:
                line = f"Need **{n['needed']:.0f}%** on the remaining {n['left']:g}% for {m['target']:g}%"
            st.markdown(line)
            kit.bars([{"label": "Marked", "frac": n["done_weight"] / 100, "colour": colour,
                       "value": f"{n['done_weight']:g}% · {n['secured']:.1f}% banked"}])
        if st.toggle("Assessments and settings", key=f"gr_open_{m['id']}"):
            _assessments(m)
            _module_settings(m)


def _add_module(expanded):
    with st.expander("Add a module", icon=":material/add:", expanded=expanded):
        with st.form("gr_new", clear_on_submit=True, border=False):
            x, y, z, w, v = st.columns([3, 1, 1, 2, 1])
            name = x.text_input("Module")
            code = y.text_input("Code")
            credits = z.number_input("Credits", 1.0, 200.0, 15.0)
            year = w.text_input("Year", placeholder="e.g. Year 2")
            target = v.number_input("Target %", 0.0, 100.0, None)
            if st.form_submit_button("Add module", type="primary"):
                try:
                    gr.add_module(name, credits, year.strip() or None, target, code.strip() or None)
                    st.rerun()
                except gr.GradeError as e:
                    st.error(str(e))


def _settings(ms, s):
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


def render_page():
    st.title("Grades")
    ms = gr.modules()
    o = gr.overall()
    s = gr.settings()
    if ms:
        _stats(ms, o, s)
        a, b = st.columns([3, 2])
        with a, kit.card("Modules at a glance"):
            _chart(ms)
            if len(o["years"]) > 1:
                kit.pills([(f"{y}: {v:.1f}%", _band(v)[1]) for y, v in o["years"].items()])
        with b, kit.card("Coming up"):
            _coming_up(ms)
        years = list(dict.fromkeys(m["year"] or "Other" for m in ms))
        for year in sorted(years, reverse=True):
            these = [m for m in ms if (m["year"] or "Other") == year]
            if len(years) > 1:
                avg = o["years"].get(year)
                kit.section(year + (f" · {avg:.1f}%" if avg is not None else ""))
            for i in range(0, len(these), 2):
                cols = st.columns(2)
                for col, m in zip(cols, these[i:i + 2]):
                    with col:
                        _module_card(m)
    else:
        kit.empty("No modules yet. Add your first one below.", ":material/school:")
    _add_module(not ms)
    _settings(ms, s)


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
