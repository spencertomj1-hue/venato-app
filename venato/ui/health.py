"""The Health data page (charts of the imported numbers, and the imports) and its Home widget.
The data and the file readers are in venato/blocks/health.py."""

from datetime import timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from venato import store
from venato import undo
from venato.blocks import health as hl


def _charts(today):
    span = st.segmented_control("Show", ["30 days", "90 days", "1 year"], default="30 days", key="hl_span") or "30 days"
    days = {"30 days": 30, "90 days": 90, "1 year": 365}[span]
    first = today - timedelta(days=days - 1)
    shown = 0
    avg = hl.latest(7)
    if avg:
        cols = st.columns(min(4, len(avg)))
        for i, (m, v) in enumerate(avg.items()):
            label, unit, _ = hl.METRICS[m]
            cols[i % len(cols)].metric(f"{label} (7-day avg)", f"{v:,.0f}" if v >= 100 else f"{v:.1f}",
                                       help=unit or None)
    pair = st.columns(2)
    for m, (label, unit, _) in hl.METRICS.items():
        s = hl.series(m, first, today)
        if not s:
            continue
        df = pd.DataFrame({"date": pd.to_datetime(list(s)), "value": list(s.values())})
        fig = (px.bar if m in ("steps", "active_kcal", "sleep_h", "distance_km", "strain") else px.line)(
            df, x="date", y="value", height=220, labels={"value": unit or label, "date": ""}, title=label)
        fig.update_layout(margin=dict(l=0, r=0, t=40, b=0))
        fig.update_xaxes(tickformat="%-d %b")
        with pair[shown % 2]:
            st.plotly_chart(fig, width="stretch", key=f"hl_c_{m}")
        shown += 1
    if not shown:
        st.info("No health data yet. Import an export in the Import tab.")


def _apple():
    st.markdown("**Apple Health**")
    st.caption("On your iPhone: Health app → your picture → Export All Health Data. Send the export.zip to this "
               "computer. Big exports (over 200 MB) work best from a file path rather than an upload.")
    since = st.date_input("Only from", store.local_today() - timedelta(days=365), key="hl_ap_since",
                          help="Older data is skipped, which makes big exports much faster")
    up = st.file_uploader("export.zip or export.xml", type=["zip", "xml"], key="hl_ap_up")
    path = st.text_input("…or the file's path on this computer", key="hl_ap_path", placeholder="~/Downloads/export.zip")
    if st.button("Import Apple Health", key="hl_ap_go", icon=":material/upload:", disabled=not (up or path.strip())):
        src = up
        if not up:
            p = Path(path.strip().strip("'\"")).expanduser()
            if not p.is_file() or p.suffix.lower() not in (".zip", ".xml"):
                st.error("That isn't a .zip or .xml file.")
                return
            if p.stat().st_size > hl.MAX_FILE:
                st.error("That file is too big.")
                return
            src = p
        with st.spinner("Reading the export (a big one takes a minute)…"):
            try:
                undo.checkpoint("Imported Apple Health")
                r = hl.import_apple(src, since)
                st.success(f"Imported {r['days']} days and {r['workouts']} new workouts.")
            except hl.HealthError as e:
                st.error(str(e))


def _csv():
    st.markdown("**Google Fit, Strava, Whoop**")
    st.caption("Google Fit: Google Takeout → Fit → \"Daily activity metrics.csv\". Strava: Settings → My Account → "
               "Download your data → activities.csv. Whoop: app → Settings → Data export → "
               "physiological_cycles.csv (daily numbers) or workouts.csv.")
    profile = st.selectbox("What is it?", list(hl.PROFILES), key="hl_prof",
                           format_func=lambda p: {"Whoop": "Whoop daily (physiological_cycles / sleeps)",
                                                  "Whoop workouts": "Whoop workouts"}.get(p, p))
    f = st.file_uploader("CSV file", type=["csv"], key=f"hl_csv_{profile}")
    if not f:
        return
    try:
        cols, rows = hl.read_csv(f.getvalue())
    except hl.HealthError as e:
        st.error(str(e))
        return
    guess = hl.guess_mapping(profile, cols)
    opts = [""] + cols
    st.caption("Check the columns (guessed from their names):")
    mapping = {}
    fields = [k for k in hl.PROFILES[profile] if k != "kind"]
    grid = st.columns(min(4, len(fields)))
    names = {"date": "Date", "title": "Name", "type": "Type", "id": "Id", "minutes": "Duration",
             "km": "Distance", "kcal": "Calories", **{m: hl.METRICS[m][0] for m in hl.METRICS}}
    for i, k in enumerate(fields):
        mapping[k] = grid[i % len(grid)].selectbox(names.get(k, k), opts, opts.index(guess[k]) if guess[k] in opts else 0,
                                                   key=f"hl_map_{profile}_{k}") or None
    metrics, workouts, problems = hl.convert(profile, rows[:2000], mapping)
    if hl.PROFILES[profile]["kind"] == "metrics":
        st.caption(f"{len({m[0] for m in metrics})} days in the first {min(len(rows), 2000)} rows")
        if metrics:
            df = pd.DataFrame(metrics, columns=["date", "metric", "value"]).pivot_table(
                index="date", columns="metric", values="value", aggfunc="last").reset_index()
            st.dataframe(df.tail(10), hide_index=True, width="stretch")
    else:
        st.caption(f"{len(workouts)} workouts in the first {min(len(rows), 2000)} rows")
        if workouts:
            st.dataframe(pd.DataFrame(workouts).drop(columns=["id"]).head(10), hide_index=True, width="stretch")
    if problems:
        with st.expander(f"{len(problems)} rows skipped"):
            st.write("\n".join(problems[:30]))
    if (metrics or workouts) and st.button(f"Import {len(rows)} rows", type="primary", key=f"hl_go_{profile}"):
        undo.checkpoint(f"Imported {profile}")
        r = hl.import_csv(profile, rows, mapping)
        st.success(f"Imported {r['values']} values and {r['workouts']} new workouts.")


def _manage():
    c = hl.counts()
    if not c:
        return
    st.markdown("**Imported so far**")
    for src, (m, w) in c.items():
        x, y = st.columns([4, 1], vertical_alignment="center")
        x.markdown(f"{src}: {m} values, {w} workouts")
        if y.button("Remove", key=f"hl_clear_{src}", icon=":material/delete:"):
            undo.checkpoint(f"Removed the {src} import")
            hl.clear(src)
            st.rerun()


def render_page():
    st.title("Health data")
    today = store.local_today()
    tabs = st.tabs(["Overview", "Import"])
    with tabs[0]:
        _charts(today)
    with tabs[1]:
        _apple()
        st.divider()
        _csv()
        st.divider()
        _manage()


def render_home():
    st.markdown("**Health**")
    avg = hl.latest(7)
    st.caption(" · ".join(hl._fmt(m, v) for m, v in list(avg.items())[:4]) + " (7-day avg)" if avg
               else "No health data imported yet.")
