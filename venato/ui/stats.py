"""
The Stats page: averages and charts of mood, energy, productivity, sleep and water, habit completion,
then anything blocks add (EXTRAS), then past weekly reviews.
"""

import pandas as pd
import plotly.express as px
import streamlit as st

from venato import regional
from venato.store import entries_between, get_stats
from venato.ui import review as review_ui

EXTRAS = []     # more sections, as functions drawing them (a block can add one: the private copy's Uni stats)


DAY_MS = 24 * 60 * 60 * 1000   # Plotly measures date steps in milliseconds


def _date_axis(fig, stats):
    """Show the whole period with plain '26 Oct' dates, a tick per day / week / month."""
    days = stats["days"]
    step = DAY_MS if days <= 14 else 7 * DAY_MS if days <= 90 else "M1"
    start, end = pd.Timestamp(stats["start"]), pd.Timestamp(stats["end"])
    fig.update_xaxes(
        title=None, tickformat="%-d %b", dtick=step, tick0=start, hoverformat="%a %-d %b",
        range=[start - pd.Timedelta(hours=12), end + pd.Timedelta(hours=12)],
    )


def page_stats():
    st.header("Stats", anchor=False)
    periods = {"Last 7 days": 7, "Last 30 days": 30, "Last 90 days": 90, "All time": None}
    period = st.radio("Period", list(periods), index=1, horizontal=True)

    # Same numbers the assistant's get_stats tool reports.
    stats = get_stats(periods[period])
    entries = entries_between(stats["start"], stats["end"])
    entries["date"] = pd.to_datetime(entries["date"])
    for col in ("mood", "sleep", "energy", "productivity", "water"):
        entries[col] = pd.to_numeric(entries[col]) if col in entries else pd.Series(dtype=float)

    # --- Averages ---
    def fmt(value, unit=""):
        return f"{value:.1f}{unit}" if value is not None else "–"

    a, b, c, p, d = st.columns(5)
    a.metric("Avg mood", fmt(stats["avg_mood"], "/10"))
    b.metric("Avg sleep", fmt(stats["avg_sleep"], " h"))
    c.metric("Avg energy", fmt(stats["avg_energy"], "/10"))
    p.metric("Avg productivity", fmt(stats["avg_productivity"], "/10"))
    d.metric("Avg water", regional.water_text(None if stats["avg_water"] is None else round(stats["avg_water"], 1)))

    # --- Line charts ---
    if entries.empty:
        st.info("No entries in this period yet.")
    else:
        # Mood, energy and productivity share a 1-10 scale, so they go on the same chart.
        fig = px.line(
            entries, x="date", y=["mood", "energy", "productivity"], markers=True,
            title="Mood, energy & productivity", labels={"value": "Score (1-10)", "variable": ""},
        )
        fig.update_yaxes(range=[0.5, 10.5], dtick=1, tickformat="d")
        _date_axis(fig, stats)
        st.plotly_chart(fig, width="stretch")

        # Whole hours from 0, so a few nights of similar sleep don't zoom into 7.1, 7.2...
        top = max(10, int(entries["sleep"].max() or 0) + 2)
        fig = px.line(entries, x="date", y="sleep", markers=True, title="Sleep",
                      labels={"sleep": "Hours"})
        fig.update_yaxes(range=[0, top], dtick=1 if top <= 12 else 2, tickformat="d")
        _date_axis(fig, stats)
        st.plotly_chart(fig, width="stretch")

        water = entries.dropna(subset=["water"]).assign(water=lambda df: df["water"].map(regional.water_out))
        if not water.empty:
            fig = px.bar(water, x="date", y="water", title="Water", labels={"water": regional.water_unit().capitalize()},
                         color_discrete_sequence=["#3E8EF7"])
            fig.update_yaxes(rangemode="tozero")
            _date_axis(fig, stats)
            st.plotly_chart(fig, width="stretch")

    # --- Habit completion % ---
    if stats["habit_completion_pct"]:
        completion = pd.DataFrame(
            {"habit": list(stats["habit_completion_pct"]), "percent": list(stats["habit_completion_pct"].values())}
        )
        fig = px.bar(completion, x="habit", y="percent", text_auto=".0f",
                     title=f"Habit completion ({stats['days']} days)",
                     labels={"percent": "% of days", "habit": ""})
        fig.update_yaxes(range=[0, 100], dtick=20, ticksuffix="%")
        st.plotly_chart(fig, width="stretch")

    for extra in EXTRAS:
        extra()
    st.divider()
    review_ui.history()                        # weekly reviews, newest first (at the bottom of Stats)
