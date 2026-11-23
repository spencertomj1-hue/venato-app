"""
The Review page. Week: one week's review in three columns that fit the window (ui/review.py render),
with a ‹ week › stepper. Trends: the last 8 weeks, then time planned vs done and (with Daily Log on)
habits, and sleep and water (when switched on) over a period, then anything blocks add (EXTRAS).
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

    if blocks.is_on("habits"):
        _habit_chart(stats)
    if not blocks.is_on("log"):             # sleep and water are Daily Log's
        return

    entries = entries_between(stats["start"], stats["end"])
    entries["date"] = pd.to_datetime(entries["date"])
    sleep_on, water_on = store.tracks_sleep(), store.tracks_water()
    for col in ("sleep", "water"):
        entries[col] = pd.to_numeric(entries[col]) if col in entries else pd.Series(dtype=float)

    # --- Averages ---
    def fmt(value, unit=""):
        return f"{value:.1f}{unit}" if value is not None else "–"

    shown = [m for m, on in (("sleep", sleep_on), ("water", water_on)) if on]
    for col, m in zip(st.columns(len(shown)) if shown else [], shown):
        if m == "sleep":
            col.metric("Avg sleep", fmt(stats["avg_sleep"], " h"))
        else:
            col.metric("Avg water", regional.water_text(None if stats["avg_water"] is None else round(stats["avg_water"], 1)))

    # --- Line charts ---
    if entries.empty:
        if shown:
            st.info("No entries in this period yet.")
    elif shown:
        axis, xscale = _date_axis(stats)

        # Whole hours from 0, so a few nights of similar sleep don't zoom into 7.1, 7.2...
        if sleep_on:
            top = max(10, int(entries["sleep"].max() if entries["sleep"].notna().any() else 0) + 2)
            chart = kit.line_chart(entries, "date", "sleep", title="Sleep", x_axis=axis, x_scale=xscale, y_scale=alt.Scale(domain=[0, top]),
                                   y_axis=alt.Axis(values=list(range(0, top + 1, 1 if top <= 12 else 2)), format="d",
                                                   title="Hours"))
            kit.show(chart)

        water = entries.dropna(subset=["water"]).assign(water=lambda df: df["water"].map(regional.water_out))
        if water_on and not water.empty:
            chart = kit.bar_chart(water, "date", "water", title="Water", x_axis=axis, x_scale=xscale,
                                  y_axis=alt.Axis(title=regional.water_unit().capitalize()), colour=kit.water(),
                                  size=max(4, min(24, 620 // max(stats["days"], 1))))
            kit.show(chart)

def _habit_chart(stats):
    """Habit completion % over the period (the Habits block's)."""
    if stats["habit_completion_pct"]:
        completion = pd.DataFrame(
            {"habit": list(stats["habit_completion_pct"]), "percent": list(stats["habit_completion_pct"].values())}
        )
        kit.show(kit.bar_chart(completion, "habit", "percent", title=f"Habit completion ({stats['days']} days)",
                               labels=".0f", y_scale=alt.Scale(domain=[0, 100]),
                               y_axis=alt.Axis(values=list(range(0, 101, 20)), labelExpr="datum.value + '%'",
                                               title="% of days")))


def _days_html(days, dates, t, full=False):
    """A bar a day under a dashed 100% line, the day's letter (or name) under it: hatched where the day isn't
    confirmed, faint for today."""
    today = store.local_today()
    names = [d.strftime("%a") for d in dates]
    bars = "".join(
        f'<span><i class="{"n" if p is None else "t" if day == today else ""}" '
        f'style="height:{100 if p is None else max(8, p)}%" title="{d}: {"not confirmed" if p is None else f"{p}% followed"}"></i></span>'
        for d, day, p in zip(names, dates, days))
    letters = "".join(f'<b class="{"t" if day == today else ""}">{d if full else d[0]}</b>' for d, day in zip(names, dates))
    said = "; ".join(f"{d} {'not confirmed' if p is None else f'{p}%'}" for d, p in zip(names, days))
    return (f'<div class="vn-rv-week" role="img" aria-label="Plan followed each day (the dashed line is 100%): {said}">'
            f'<div class="vn-rv">{bars}</div><div class="vn-rv-days" aria-hidden="true">{letters}</div></div>')


def _trend_html(pcts):
    """The last weeks' Plan followed, a small bar a week (this one solid, the rest faint; hatched: nothing
    confirmed) under a dashed 100% line. CSS, not SVG: st.html strips SVG."""
    if sum(p is not None for p in pcts) < 2:
        return ""
    bars = "".join(f'<span><i class="{"n" if p is None else "t" if k < len(pcts) - 1 else ""}" '
                   f'style="height:{100 if p is None else max(8, p)}%"></i></span>' for k, p in enumerate(pcts))
    said = ", ".join("nothing confirmed" if p is None else f"{p}%" for p in pcts)
    return (f'<div class="vn-rv vn-rv-weeks" role="img" aria-label="Plan followed, last {len(pcts)} weeks, oldest first: {said}">'
            f'{bars}</div><div class="vn-rv-days" aria-hidden="true"><b>{len(pcts)} weeks ago</b><b class="t">this week</b></div>')


def render_home(size="small"):
    """Home's Review tile: the week's % of Plan followed, the change from last week, the review's verdict in words,
    and how many days still need confirming. Wide adds a bar a day; Large adds plan vs done by category and the
    last 8 weeks (Wide and Large say the hours and to-dos in the header). Most important first: on short rows Home hides whatever crosses the bottom."""
    from html import escape
    from venato import pace
    from venato import review
    t = appearance.tokens()
    tones = review_ui._tones()
    w = review.tile(trend_weeks=8 if size == "large" else 0)
    dates = pace.week_days(w["first"])
    pct, before = w["pct"], w["before"]
    delta = ""
    if pct is not None and before is not None:
        diff = pct - before
        delta = (f'<span class="vn-rv-delta" style="color:{tones["good"] if diff >= 0 else tones["bad"]}">'
                 f'{"▲" if diff > 0 else "▼" if diff < 0 else "="} {abs(diff)} vs the week before</span>')
    n = len(w["to_confirm"])
    which = " &amp; ".join(store._as_date(d).strftime("%a") for d in w["to_confirm"][:3]) + ("…" if n > 3 else "")
    chip = (f'<span class="vn-rv-chip" title="Confirm {which} on the timetable"><i></i>{n} '
            f'{"day" if n == 1 else "days"} to confirm</span>') if n else ""
    big = (f'<div class="vn-rv-big">{pct}<small>%</small></div>' if pct is not None
           else '<div class="vn-rv-big vn-rv-mut">–</div>')
    short = w["short"]
    short_line = (f'<span class="vn-rv-sh">{escape(short["category"])}</span> fell short: {short["actual"]:g} of {short["plan"]:g} h.'
                  if short else f'{escape(" and ".join(w["missed"][:2]))} missed {"its" if len(w["missed"]) == 1 else "their"} target.'
                  if w["missed"] else "")
    if pct is None:
        short_line = f"The week before: {before}% followed." if before is not None else "Confirm days on the timetable to see how the week's going."
    sentence = escape(w["sentence"]).replace(escape(short["category"]) + " fell short",
                                             f'<span class="vn-rv-sh">{escape(short["category"])}</span> fell short') \
        if short else escape(w["sentence"])
    verdict = f'<p class="vn-rv-vd"><b>{escape(w["verdict"])}.</b> {sentence}</p>'

    if size == "small":
        body = (f'<div class="vn-rv-row">{big}<div class="vn-rv-col">{delta}{chip}</div></div>'
                f'<p class="vn-rv-vd">{short_line}</p>')
    elif size == "wide":
        right = verdict + (_days_html(w["days"], dates, t) if pct is not None else "")
        body = (f'<div class="vn-rv-row vn-rv-top"><div class="vn-rv-col vn-rv-left">{big}{delta}{chip}</div>'
                f'<div class="vn-rv-col vn-rv-right">{right}</div></div>')
    else:
        top = max([1.0] + [max(c["plan"], c["actual"]) for c in w["time"]])
        cats = "".join(
            f'<div class="vn-rv-cat"><span>{escape(c["category"])}</span><span class="vn-rv-tr">'
            f'<i style="width:{100 * c["actual"] / top:.0f}%;background:{c["colour"]}"></i>'
            f'<u style="left:{100 * c["plan"] / top:.0f}%"></u></span>'
            f'<span class="{"vn-rv-sh" if c["plan"] - c["actual"] >= 1 else ""}">{c["actual"]:g} / {c["plan"]:g} h</span></div>'
            for c in w["time"][:3])
        spark = _trend_html(w["trend"])
        last = w["first"] + timedelta(days=6)
        when = f'{w["first"].day} – {last.day} {last:%b}'
        body = (f'<div class="vn-rv-row vn-rv-top"><div class="vn-rv-col vn-rv-left">{big}{delta}</div>'
                f'<div class="vn-rv-col vn-rv-right">{verdict}</div></div>'
                + ('<div class="vn-rv-split">'
                   + (f'<div><span class="vn-rv-sub">Plan vs done · {when}</span>{cats}</div>' if cats else "")
                   + (f'<div><span class="vn-rv-sub">Last 8 weeks</span>{spark}</div>' if spark else "")
                   + '</div>' if cats or spark else "")
                + (f'<div class="vn-rv-row vn-rv-end"><div class="vn-rv-grow">{_days_html(w["days"], dates, t, full=True)}</div>{chip}</div>'
                   if pct is not None or n else ""))
    st.html(f"""<style>
      .vn-rv-tile {{ display: flex; flex-direction: column; gap: 6px; color: {t['ink']}; }}
      .vn-rv-row {{ display: flex; gap: 14px; align-items: center; min-width: 0; }}
      .vn-rv-top {{ align-items: flex-start; }} .vn-rv-end {{ align-items: flex-end; }}
      .vn-rv-col {{ display: flex; flex-direction: column; gap: 4px; min-width: 0; }}
      .vn-rv-left {{ width: 140px; flex: none; }} .vn-rv-right, .vn-rv-grow {{ flex: 1; min-width: 0; }}
      .vn-rv-big {{ font-size: 2.3rem; font-weight: 700; line-height: 1; letter-spacing: -0.02em; font-variant-numeric: tabular-nums; }}
      .vn-rv-big small {{ font-size: 0.95rem; font-weight: 500; color: {t['muted']}; margin-left: 2px; }}
      .vn-rv-mut {{ color: {t['muted']}; }}
      .vn-rv-delta {{ font-size: 0.78rem; font-weight: 600; white-space: nowrap; }}
      .vn-rv-chip {{ display: inline-flex; align-items: center; gap: 6px; font-size: 0.76rem; font-weight: 500; width: fit-content;
        white-space: nowrap; border-radius: 999px; padding: 3px 10px; background: {t['track']}; }}
      .vn-rv-chip i {{ width: 7px; height: 7px; border-radius: 50%; background: {tones['amber']}; }}
      .vn-rv-vd {{ font-size: 0.86rem; line-height: 1.35; margin: 0; }}
      .vn-rv-vd b {{ font-weight: 700; }}
      .vn-rv-sh {{ color: {tones['bad']}; font-weight: 600; }}
      .vn-rv {{ height: 28px; display: flex; gap: 6px; align-items: flex-end; border-top: 1px dashed {t['muted']}88; }}
      .vn-rv span {{ flex: 1; height: 100%; display: flex; align-items: flex-end; }}
      .vn-rv i {{ width: 100%; border-radius: 4px; background: {t['accent']}; }}
      .vn-rv i.t {{ opacity: 0.45; }}
      .vn-rv i.n {{ background: repeating-linear-gradient(135deg, rgba(128,128,128,0.25) 0 3px, transparent 3px 6px);
        border: 1px dashed {t['muted']}; box-sizing: border-box; }}
      .vn-rv-days {{ display: flex; gap: 6px; margin-top: 3px; }}
      .vn-rv-days b {{ flex: 1; text-align: center; font-size: 0.62rem; font-weight: 500; color: {t['muted']}; line-height: 1; }}
      .vn-rv-days b.t {{ color: {t['ink']}; font-weight: 700; }}
      .vn-rv-split {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
      .vn-rv-split > div {{ display: flex; flex-direction: column; gap: 5px; min-width: 0; }}
      .vn-rv-sub {{ font-size: 0.66rem; font-weight: 600; letter-spacing: 0.07em; text-transform: uppercase; color: {t['muted']}; }}
      .vn-rv-cat {{ display: grid; grid-template-columns: minmax(0, 74px) 1fr auto; gap: 8px; align-items: center; font-size: 0.78rem; }}
      .vn-rv-cat > span:first-child {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
      .vn-rv-cat > span:last-child {{ font-variant-numeric: tabular-nums; color: {t['muted']}; white-space: nowrap; }}
      .vn-rv-cat > span.vn-rv-sh {{ color: {tones['bad']}; }}
      .vn-rv-tr {{ height: 8px; background: {t['track']}; border-radius: 4px; position: relative; }}
      .vn-rv-tr i {{ position: absolute; inset: 0 auto 0 0; border-radius: 4px; }}
      .vn-rv-tr u {{ position: absolute; top: -2px; bottom: -2px; width: 2px; margin-left: -1px; background: {t['muted']}; }}
      .vn-rv-weeks {{ height: 52px; gap: 4px; }} .vn-rv-weeks i.t {{ opacity: 0.35; }}
      .vn-rv-weeks + .vn-rv-days {{ justify-content: space-between; }} .vn-rv-weeks + .vn-rv-days b {{ flex: none; }}
      @media (max-height: 800px) {{ .vn-rv-big {{ font-size: 1.9rem; }} .vn-rv {{ height: 22px; }} }}
    </style><div class="vn-rv-tile">{body}</div>""")
