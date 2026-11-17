"""The Health data page (charts of the imported numbers, and the imports) and its Home widget.
The data and the file readers are in venato/blocks/health.py."""

from datetime import timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from venato import store
from venato import undo
from venato.blocks import health as hl
from venato.ui import kit


COLOUR = {"steps": "#4E79A7", "active_kcal": "#F28E2B", "distance_km": "#59A14F", "sleep_h": "#B07AA1",
          "resting_hr": "#FF9DA7", "hrv": "#76B7B2", "weight_kg": "#9C755F", "recovery": "#8CD17D",
          "strain": "#EDC948"}
# Which way is better: up ("normal"), down ("inverse") or neither ("off").
BETTER = {"resting_hr": "inverse", "weight_kg": "off", "strain": "off"}
BARS = ("steps", "active_kcal", "sleep_h", "distance_km", "strain")


def _num(v):
    return f"{v:,.0f}" if abs(v) >= 100 else f"{v:.1f}"


def _avg(s, first, last):
    vals = [v for d, v in s.items() if first <= d <= last]
    return sum(vals) / len(vals) if vals else None


def _charts(today):
    a, b = st.columns([3, 1], vertical_alignment="center")
    a.caption("Your imported numbers. Tiles show the last 7 days' average against the 7 days before.")
    span = b.segmented_control("Show", ["30 days", "90 days", "1 year"], default="30 days", key="hl_span",
                               label_visibility="collapsed", width="stretch") or "30 days"
    days = {"30 days": 30, "90 days": 90, "1 year": 365}[span]
    first = today - timedelta(days=days - 1)
    data = {}
    for m in hl.METRICS:
        s = hl.series(m, today - timedelta(days=max(days, 30) - 1), today)
        if s:
            data[m] = {store._as_date(d): v for d, v in s.items()}
    if not data:
        kit.empty("No health data yet. Import an export in the Import tab.", ":material/monitor_heart:")
        return
    tiles = []
    for m, s in data.items():
        label, unit, _ = hl.METRICS[m]
        now = _avg(s, today - timedelta(days=6), today)
        before = _avg(s, today - timedelta(days=13), today - timedelta(days=7))
        if now is None:
            continue
        spark = [s.get(today - timedelta(days=i)) for i in range(29, -1, -1)]
        delta = None if before is None else f"{'+' if now >= before else '-'}{_num(abs(now - before))} {unit}".strip()
        tiles.append({"label": label, "value": f"{_num(now)} {unit}".strip(), "delta": delta,
                      "delta_color": BETTER.get(m, "normal"), "help": "7-day average, against the week before",
                      "chart": [v or 0 for v in spark], "chart_type": "bar" if m in BARS else "line"})
    for i in range(0, len(tiles), 4):
        kit.stats(tiles[i:i + 4], per_row=4)
    shown = [m for m in data if any(first <= d for d in data[m])]
    for i in range(0, len(shown), 2):
        cols = st.columns(2)
        for col, m in zip(cols, shown[i:i + 2]):
            label, unit, _ = hl.METRICS[m]
            s = {d: v for d, v in data[m].items() if d >= first}
            df = pd.DataFrame({"date": pd.to_datetime(list(s)), "value": list(s.values())}).sort_values("date")
            df["avg"] = df["value"].rolling(7, min_periods=3).mean()
            c = COLOUR[m]
            fig = go.Figure()
            hover = "%{x|%a %-d %b}: %{y:,.1f} " + unit + "<extra></extra>"
            if m in BARS:
                fig.add_bar(x=df["date"], y=df["value"], marker_color=kit.rgba(c, 0.55), hovertemplate=hover)
            else:
                fig.add_scatter(x=df["date"], y=df["value"], mode="markers", marker=dict(color=kit.rgba(c, 0.5), size=5),
                                hovertemplate=hover)
            fig.add_scatter(x=df["date"], y=df["avg"], mode="lines", line=dict(color=c, width=3),
                            hovertemplate="7-day average: %{y:,.1f}<extra></extra>")
            fig.update_xaxes(tickformat="%-d %b")
            if m not in BARS:
                fig.update_yaxes(rangemode="normal")
            with col, kit.card(f"{label}" + (f" ({unit})" if unit else "")):
                kit.chart(fig, f"hl_c_{m}", 220)


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
    with kit.card("Imported so far", stretch=False):
        for src, (m, w) in c.items():
            x, y = st.columns([4, 1], vertical_alignment="center")
            x.markdown(f"**{src}** :gray[· {m:,} values · {w} workouts]")
            with y.popover("Remove", icon=":material/delete:", width="stretch"):
                st.warning(f"Remove everything imported from {src}?")
                if st.button("Remove", key=f"hl_clear_{src}", type="primary"):
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
        a, b = st.columns(2)
        with a, kit.card():
            _apple()
        with b, kit.card():
            _csv()
        _manage()


def render_home():
    st.markdown("**Health**")
    avg = hl.latest(7)
    st.caption(" · ".join(hl._fmt(m, v) for m, v in list(avg.items())[:4]) + " (7-day avg)" if avg
               else "No health data imported yet.")
