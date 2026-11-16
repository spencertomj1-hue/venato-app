"""
Extra Stats sections (added to Stats through stats.EXTRAS by blocks/personal.py): the user's
own day trackers, runs (Strava and training), and gym volume.
"""

import pandas as pd
import plotly.express as px
import streamlit as st

from venato import store
from venato.ui.stats import _date_axis


def render(stats):
    _tracker_charts(stats)
    _runs_chart(stats)
    _gym_volume_chart()


render.wants_stats = True        # stats.page_stats passes the chosen period


def _tracker_charts(stats):
    """Each of the user's day trackers: the period's total and a bar per day (blank days count as 0)."""
    trackers = store.day_trackers()
    if not trackers:
        return
    st.subheader("Trackers", anchor=False)
    rows = store.day_values_between(stats["start"], stats["end"])
    if not rows:
        st.caption("Log your trackers on the journal's left page (Daily Log) to see them here.")
        return
    days = pd.date_range(stats["start"], stats["end"], freq="D")
    columns = st.columns(min(len(trackers), 4))
    for i, t in enumerate(trackers):
        values = {d: v for d, tid, v in rows if tid == t["id"]}
        unit = t["unit"] or "times"
        total = sum(values.values())
        columns[i % len(columns)].metric(f"{t['name']} ({stats['days']} days)", f"{total:g} {unit}",
                                         help=f"Logged on {sum(v > 0 for v in values.values())} of {stats['days']} days")
    for t in trackers:
        values = {d: v for d, tid, v in rows if tid == t["id"]}
        if not any(values.values()):
            continue
        unit = t["unit"] or "times"
        df = pd.DataFrame({"date": days, "value": [values.get(d.date().isoformat(), 0) for d in days]})
        fig = px.bar(df, x="date", y="value", title=f"{t['name']} per day", labels={"value": unit.capitalize(), "date": ""})
        fig.update_traces(hovertemplate=f"%{{x|%a %d %b}}: %{{y:g}} {unit}<extra></extra>")
        _date_axis(fig, stats)
        st.plotly_chart(_accent_bars(fig), width="stretch")


def _accent_bars(fig):
    """One series: the app's accent colour, thin rounded bars, quiet grid."""
    fig.update_traces(marker_color=st.get_option("theme.primaryColor") or "#ff4b4b", marker_cornerradius=4)
    fig.update_layout(bargap=0.35, showlegend=False, margin=dict(t=50, b=10))
    fig.update_yaxes(gridcolor="rgba(128,128,128,0.18)", zeroline=False)
    fig.update_xaxes(showgrid=False)
    return fig


def _labels(dates):
    """'5 Nov' per run, numbered when there are two on a day ('5 Nov (2)')."""
    seen, out = {}, []
    for d in dates:
        day = pd.Timestamp(d)
        base = f"{day.day} {day:%b}"
        seen[base] = seen.get(base, 0) + 1
        out.append(base if seen[base] == 1 else f"{base} ({seen[base]})")
    return out


def _runs_chart(stats):
    """Every run in the period (Strava, plus training runs ticked off by hand) and its distance."""
    runs = store.runs(stats["start"], stats["end"])
    st.subheader("Runs", anchor=False)
    if not runs:
        st.caption("No runs in this period yet. Tick off training runs, or connect Strava in Settings → Strava.")
        return
    df = pd.DataFrame(runs)
    df["run"] = _labels(df["date"])
    df["day"] = pd.to_datetime(df["date"]).dt.strftime("%a %d %b")
    total, longest = df["distance_km"].sum(), df["distance_km"].max()
    a, b, c = st.columns(3)
    a.metric("Runs", len(df))
    b.metric("Distance", f"{total:.1f} km")
    c.metric("Longest", f"{longest:.1f} km")
    fig = px.bar(df, x="run", y="distance_km", title="Distance per run",
                 labels={"run": "", "distance_km": "km"}, custom_data=["label", "day", "source"])
    fig.update_traces(hovertemplate="<b>%{customdata[0]}</b><br>%{customdata[1]}<br>%{y:.2f} km"
                                    "<br><span style='opacity:.7'>%{customdata[2]}</span><extra></extra>")
    fig.update_xaxes(type="category", categoryorder="array", categoryarray=list(df["run"]))
    st.plotly_chart(_accent_bars(fig), width="stretch")


def _gym_volume_chart():
    """Progressive overload: kg moved per session (weight × sets × reps) for one exercise."""
    rows = store.gym_volume()
    st.subheader("Gym: progressive overload", anchor=False)
    if not rows:
        st.caption("Log gym sessions on the Training page to see your volume grow here.")
        return
    df = pd.DataFrame(rows)
    df["key"] = df["exercise"].str.lower()
    counts = df.groupby("key")["exercise"].agg(["count", "first"]).sort_values("count", ascending=False)
    names = dict(zip(counts.index, counts["first"]))
    pick = st.selectbox("Exercise", list(names), format_func=names.get, key="stats_gym_exercise")
    one = df[df["key"] == pick].reset_index(drop=True)
    one["when"] = _labels(one["date"])
    if len(one) >= 2:
        last, prev = one["volume"].iloc[-1], one["volume"].iloc[-2]
        best = one["volume"].max()
        change = f"{(last - prev) / prev:+.0%} vs the session before" if prev else "first session with weight"
        a, b = st.columns(2)
        a.metric("Last session", f"{last:,.0f} kg", change, delta_color="normal")
        b.metric("Best session", f"{best:,.0f} kg")
    fig = px.bar(one, x="when", y="volume", title=f"{names[pick]}: kg moved per session (weight × sets × reps)",
                 labels={"when": "", "volume": "kg"}, custom_data=["title"])
    fig.update_traces(hovertemplate="<b>%{x}</b> · %{customdata[0]}<br>%{y:,.0f} kg<extra></extra>")
    fig.update_xaxes(type="category", categoryorder="array", categoryarray=list(one["when"]))
    st.plotly_chart(_accent_bars(fig), width="stretch")
