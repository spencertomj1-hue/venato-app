"""
The Stats page: averages and charts of mood, energy, productivity, sleep and water, habit completion,
then anything blocks add (EXTRAS), then past weekly reviews.
"""

import altair as alt
import pandas as pd
import streamlit as st

from venato import regional
from venato.store import entries_between, get_stats
from venato.ui import kit
from venato.ui import review as review_ui

EXTRAS = []     # more sections, as functions drawing them (a block can add one: the private copy's Uni stats)


def _date_axis(stats):
    """(axis, scale) showing the whole period with plain '26 Oct' dates, a tick per day / week / month."""
    days = stats["days"]
    step = "day" if days <= 14 else "week" if days <= 90 else "month"
    start, end = pd.Timestamp(stats["start"]), pd.Timestamp(stats["end"])
    axis = alt.Axis(format=kit.DAY_FORMAT, tickCount=step, labelOverlap=True, grid=False, labelAngle=0)
    scale = alt.Scale(domain=[(start - pd.Timedelta(hours=12)).isoformat(), (end + pd.Timedelta(hours=12)).isoformat()])
    return axis, scale


def page_stats():
    st.header("Review", anchor=False)
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
        axis, xscale = _date_axis(stats)

        # Mood, energy and productivity share a 1-10 scale, so they go on the same chart.
        chart = kit.line_chart(entries, "date", ["mood", "energy", "productivity"], y_title="Score (1-10)",
                               title="Mood, energy & productivity", x_axis=axis, x_scale=xscale,
                               y_scale=alt.Scale(domain=[0.5, 10.5]), y_axis=alt.Axis(values=list(range(1, 11)),
                                                                                       format="d", title="Score (1-10)", labelOverlap=False))
        kit.show(chart)

        # Whole hours from 0, so a few nights of similar sleep don't zoom into 7.1, 7.2...
        top = max(10, int(entries["sleep"].max() or 0) + 2)
        chart = kit.line_chart(entries, "date", "sleep", title="Sleep", x_axis=axis, x_scale=xscale, y_scale=alt.Scale(domain=[0, top]),
                               y_axis=alt.Axis(values=list(range(0, top + 1, 1 if top <= 12 else 2)), format="d",
                                               title="Hours"))
        kit.show(chart)

        water = entries.dropna(subset=["water"]).assign(water=lambda df: df["water"].map(regional.water_out))
        if not water.empty:
            chart = kit.bar_chart(water, "date", "water", title="Water", x_axis=axis, x_scale=xscale,
                                  y_axis=alt.Axis(title=regional.water_unit().capitalize()), colour=kit.water(),
                                  size=max(4, min(24, 620 // max(stats["days"], 1))))
            kit.show(chart)

    # --- Habit completion % ---
    if stats["habit_completion_pct"]:
        completion = pd.DataFrame(
            {"habit": list(stats["habit_completion_pct"]), "percent": list(stats["habit_completion_pct"].values())}
        )
        kit.show(kit.bar_chart(completion, "habit", "percent", title=f"Habit completion ({stats['days']} days)",
                               labels=".0f", y_scale=alt.Scale(domain=[0, 100]),
                               y_axis=alt.Axis(values=list(range(0, 101, 20)), labelExpr="datum.value + '%'",
                                               title="% of days")))

    # --- Timetable: planned vs done, on confirmed days only ---
    hours = stats["timetable_hours"]
    rows = [{"Category": cat, "Hours": h, "Track": label}
            for track, label in (("plan", "Planned"), ("actual", "Done")) for cat, h in hours[track].items()]
    if rows:
        kit.show(kit.bar_chart(pd.DataFrame(rows), "Category", "Hours", color="Track", title="Time: planned vs done",
                               labels=".1f", palette={"Planned": kit.muted(), "Done": review_ui.regional_accent()}))
    st.caption(f"Timetable time is counted from the {stats['days_confirmed']} of {stats['days']} days you've "
               "confirmed. Confirm a day on the Timetable, or from Home's end-of-day prompt.")

    for extra in EXTRAS:
        extra()
    st.divider()
    review_ui.history()                        # weekly reviews, newest first (at the bottom of Stats)
