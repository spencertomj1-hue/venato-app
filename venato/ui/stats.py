"""
The Review page. Week: one week's review in three columns that fit the window (ui/review.py render),
with a ‹ week › stepper. Trends: the last 8 weeks, then time planned vs done and (with Daily Log on)
mood, energy, productivity, sleep, water and habits over a period, then anything blocks add (EXTRAS).
"""

from datetime import timedelta


import altair as alt
import pandas as pd
import streamlit as st

from venato import blocks, regional
from venato import store
from venato.store import entries_between, get_stats
from venato.ui import appearance, kit, timetable_tools
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


VIEWS = ["Week", "Trends"]
# The Week view fits the window: less top padding than other pages, and the columns fill the height left
# (minus the chat bar's room when it's there).
_FIT = """<style>
.stMainBlockContainer {{ padding-top: 1.1rem !important; padding-bottom: 0.5rem !important; }}
[data-testid="stHeader"], [data-testid="stHeader"] > * {{ background: transparent !important; box-shadow: none !important;
    pointer-events: none; }}
[data-testid="stHeader"] button, [data-testid="stHeader"] a {{ pointer-events: auto; }}
.st-key-rv_page > [data-testid="stLayoutWrapper"]:has([class*="_cols"]) {{
    height: calc(100dvh - 1.1rem - 92px - {bottom}); flex: none; }}
.st-key-rv_page > [data-testid="stLayoutWrapper"] :is([data-testid="stLayoutWrapper"], [data-testid="stVerticalBlock"]):has([class*="_cols"]),
.st-key-rv_page [class*="st-key-review_"][class*="_cols"] {{ height: 100%; flex: none; }}
</style>"""
_HEAD = """<style>
.st-key-rv_head .rv-title { font-family: var(--venato-serif); font-size: 2.3rem; font-weight: 600; line-height: 1.1;
                            margin-right: .4rem; }
.st-key-rv_step { border: 1px solid rgba(128,128,128,.3); border-radius: .6rem; padding: 0 .2rem; }
.st-key-rv_view_w button[aria-checked="true"] { background: #1F1E1C !important; border-color: #1F1E1C !important; }
.st-key-rv_view_w button[aria-checked="true"] p { color: #F6F4EF !important; }
.st-key-rv_step .rv-wk { font-weight: 600; font-variant-numeric: tabular-nums; min-width: 8.5rem; text-align: center;
                       display: block; }
</style>"""


def _this_week():
    return store.week_start_of(store.local_today())


def _stepper_title(first):
    """'9 – 15 Nov 2026' (or '30 Nov – 6 Dec 2026' across months)."""
    last = first + timedelta(days=6)
    start = str(first.day) if first.month == last.month else regional.day_month(first, weekday=False)
    return f"{start} – {regional.day_month(last, weekday=False, year=True)}"


def _step(weeks):
    st.session_state["rv_week"] = min(_this_week(), st.session_state["rv_week"] + timedelta(weeks=weeks))


def _keep_view():
    st.session_state["rv_view"] = st.session_state["rv_view_w"] or "Week"


def page_stats():
    sess = st.session_state
    this_week = _this_week()
    week = sess["rv_week"] = min(sess.get("rv_week") or this_week, this_week)
    view = sess.setdefault("rv_view", "Week")
    sess["rv_view_w"] = view                       # the widget's state goes when another page is open
    if view == "Week":
        st.html(_FIT.format(bottom="5.5rem" if store.ai_enabled() else "0.5rem"))
    st.html(_HEAD)
    if appearance.is_dark():                       # the chosen view: light on dark
        st.html("<style>.st-key-rv_view_w button[aria-checked='true'] { background: #E8E8EC !important; border-color: #E8E8EC !important; }"
                ".st-key-rv_view_w button[aria-checked='true'] p { color: #1F1E1C !important; }</style>")
    with st.container(key="rv_page", gap="medium"):
        with st.container(key="rv_head", horizontal=True, vertical_alignment="center", gap="small"):
            st.html('<div class="rv-title">Review</div>', width="content")
            if view == "Week":
                with st.container(key="rv_step", horizontal=True, vertical_alignment="center", gap=None,
                                  width="content"):
                    st.button("", key="rv_prev", icon=":material/chevron_left:", type="tertiary",
                              on_click=_step, args=(-1,), help="The week before")
                    st.html(f'<span class="rv-wk">{_stepper_title(week)}</span>', width="content")
                    st.button("", key="rv_next", icon=":material/chevron_right:", type="tertiary",
                              on_click=_step, args=(1,), disabled=week >= this_week, help="The week after")
            st.segmented_control("View", VIEWS, key="rv_view_w", required=True, on_change=_keep_view,
                                 label_visibility="collapsed")
            with st.container(horizontal=True, horizontal_alignment="right"):
                if view == "Week":
                    review_ui.ask_button(week, "rv")
        if view == "Week":
            st.fragment(review_ui.render)(week, key=f"review_{week.isoformat()}", page=True)
        else:
            review_ui.trends(week)
            _charts()
            for extra in EXTRAS:
                extra()


@st.fragment
def _charts():
    """The period's averages and charts: a fragment, so picking another period redraws just these."""
    periods = {"Last 7 days": 7, "Last 30 days": 30, "Last 90 days": 90, "All time": None}
    period = st.radio("Period", list(periods), index=1, horizontal=True, key="stats_period")

    # Same numbers the assistant's get_stats tool reports.
    stats = get_stats(periods[period])
    # --- Timetable: planned vs done, on confirmed days only ---
    hours = stats["timetable_hours"]
    rows = [{"Category": cat, "Hours": h, "Track": label}
            for track, label in (("plan", "Planned"), ("actual", "Done")) for cat, h in hours[track].items()]
    if rows:
        kit.show(kit.bar_chart(pd.DataFrame(rows), "Category", "Hours", color="Track", title="Time: planned vs done",
                               labels=".1f", palette={"Planned": kit.muted(), "Done": review_ui.regional_accent()}))
    if not rows and store.load_categories().empty:
        timetable_tools.no_categories("stats_addcat", "You have no categories yet, so there's no time to compare.")
    st.caption(f"Timetable time is counted from the {stats['days_confirmed']} of {stats['days']} days you've "
               "confirmed. Confirm a day on the Timetable, or from Home's end-of-day prompt.")

    if not blocks.is_on("log"):             # mood, sleep, water and habits are Daily Log's
        return

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
        top = max(10, int(entries["sleep"].max() if entries["sleep"].notna().any() else 0) + 2)
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
