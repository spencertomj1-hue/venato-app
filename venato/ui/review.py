"""
The weekly review on screen, in three columns (render): the verdict and looking back; goal pace and
next week; time planned vs done. It's the Review page's Week view (ui/stats.py), and a pop-up the first
time Venato is opened after 7pm on Sunday (maybe_show). The numbers come from venato/review.py.
"""

from datetime import timedelta
from html import escape

import altair as alt
import pandas as pd
import streamlit as st

from venato import blocks, pace, regional
from venato import review
from venato import store
from venato.ui import kit


def _week_title(first):
    last = first + timedelta(days=6)
    return f"{regional.day_month(first, weekday=False)} – {regional.day_month(last, weekday=False, year=True)}"


POPUP = "review_popup"
KEPT = {"yes": "Yes", "partly": "Partly", "no": "No"}


def _save_kept(first, key):
    pick = st.session_state.get(key)
    store.save_review(first, kept=next((k for k, v in KEPT.items() if v == pick), None))


def _whole_app(key):
    """After a callback that changes something outside the review (the chat, the timetable, the page):
    on Review the review is a fragment, so rerun the whole app (the pop-up's rerun already is)."""
    if key != POPUP:
        st.rerun(scope="app")


def _ask_claude(first, key):
    from venato.ui import chat
    chat.ask(f"Review my week of {_week_title(first)} (weekly_review with date {first.isoformat()}). "
             "Give me an honest verdict in a few lines: what went well, what slipped and why, "
             "and one concrete thing to change next week.")
    _whole_app(key)


def ask_button(first, key):
    """"Ask Claude" about the week (only with Claude switched on)."""
    if store.ai_enabled():
        st.button("Ask Claude", key=f"{key}_ask", icon=":material/auto_awesome:", on_click=_ask_claude,
                  args=(first, key), help="Claude reads this week's numbers and gives you its take in the chat")


def _confirm_days(days, key):
    for d in days:
        store.confirm_day(d)
    st.toast(f"Confirmed {len(days)} day{'s' if len(days) != 1 else ''}", icon=":material/task_alt:")
    _whole_app(key)


def _open_day(day, key):
    from venato.ui import timetable
    timetable._review(store._as_date(day))
    _whole_app(key)


VERDICT = {"Strong": "good", "Solid": "good", "Patchy": "amber", "Rough": "bad"}
STATE_TONE = {"done": "good", "on_track": "good", "behind": "amber", "slipping": "amber", "unreachable": "bad",
              "ended": "muted", "upcoming": "muted"}


def _tones():
    good, bad = kit.good_bad()
    return {"good": good, "bad": bad, "amber": kit.amber(), "muted": kit.muted()}


def _pill(text, tone, big=False):
    return kit.pill(text, _tones()[tone]).replace('class="vk-pill"', f'class="vk-pill{" rv-pill-big" if big else ""}"')


def _h(n):
    return f"{n:g}" if n == int(n) else f"{n:.1f}"


def _css(key, page):
    """The cards' look. On the Review page (`page`) the columns fill the window's height."""
    kit._css()                                     # the pills
    tones = _tones()
    k = f".st-key-{key}"
    fill = f"""
    {k}_cols > [data-testid="stLayoutWrapper"], {k}_cols [data-testid="stHorizontalBlock"] {{ height: 100%; }}
    {k}_cols [data-testid="stColumn"] > [data-testid="stVerticalBlock"] {{ height: 100%; flex-wrap: nowrap; }}
    {k}_back, {k}_next, {k}_time {{ flex: 1 1 0; min-height: 0; }}
    [data-testid="stLayoutWrapper"]:has(> {k}_goals) {{ flex: 0 1 auto; min-height: 0; max-height: 55%; }}
    {k}_goals {{ height: 100%; overflow-y: auto; }}   /* a long goal list scrolls, leaving Next week room */
    {k}_back [data-testid="stForm"] {{ flex: 1 1 0; min-height: 0; display: flex; flex-direction: column; padding: 0; }}
    {k}_back [data-testid="stForm"] > div > [data-testid="stVerticalBlock"] {{ height: 100%; }}
    {k}_back [data-testid="stElementContainer"]:has([data-testid="stTextArea"]) {{ flex: 1 1 0; min-height: 2rem; }}
    {k}_back [data-testid="stTextArea"], {k}_back [data-testid="stTextArea"] > div:last-child,
    {k}_back [data-testid="stTextArea"] [data-baseweb="textarea"] {{ height: 100%; }}
    {k}_back [data-testid="stTextArea"] {{ display: flex; flex-direction: column; }}
    {k}_back [data-testid="stTextArea"] > div:last-child {{ flex: 1 1 0; min-height: 0; }}
    {k}_back textarea {{ height: 100% !important; min-height: 0 !important; resize: none; }}
    {k}_back [data-testid="stTextArea"] label p {{ font-weight: 600; }}
    {k}_next [data-testid="stElementContainer"]:has(.rv-next),
    {k}_time [data-testid="stElementContainer"]:has(.rv-time) {{ flex: 1 1 0; min-height: 0; }}
    {k}_next [data-testid="stHtml"], {k}_time [data-testid="stHtml"], {k}_next .rv-next, {k}_time .rv-time {{
        height: 100%; }}
    {k}_time [data-testid="stHtml"] {{ overflow-y: auto; }}
    """ if page else f"{k}_back [data-testid='stTextArea'] label p {{ font-weight: 600; }}"
    st.html(f"""<style>
    {fill}
    {k}_nudge {{ background: {kit.rgba(tones["amber"], 0.10)}; border: 1px solid {kit.rgba(tones["amber"], 0.45)};
                 border-radius: 0.6rem; padding: 0.45rem 0.6rem 0.45rem 0.9rem; }}
    {k}_nudge .rv-nudge {{ color: {tones["amber"]}; font-weight: 600; }}
    .rv-h {{ font-family: var(--venato-serif); font-size: 1.2rem; font-weight: 600; line-height: 1.2; }}
    .rv-h small {{ font-family: var(--font, inherit); font-size: 0.8rem; font-weight: 400; opacity: .7; margin-left: .5rem; }}
    .rv-verdict {{ font-family: var(--venato-serif); font-size: 1.1rem; font-weight: 500; line-height: 1.3;
                   margin-top: .35rem; }}
    .rv-pill-big {{ font-size: 0.88rem; padding: 3px 12px; }}
    .rv-goals {{ display: flex; flex-direction: column; gap: 5px; margin-top: .25rem; }}
    .rv-goals > div {{ display: flex; gap: 10px; align-items: baseline; line-height: 1.25; }}
    .rv-goals b {{ font-weight: 600; }} .rv-goals .m, .rv-m {{ opacity: .68; font-size: .85rem; }}
    .rv-next {{ overflow-y: auto; }}
    .rv-next, .rv-time {{ min-height: 100%; display: flex; flex-direction: column; justify-content: space-between; gap: 10px; }}
    .rv-next section {{ display: flex; flex-direction: column; gap: 6px; }}
    .rv-cap {{ font-size: .72rem; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; opacity: .65; }}
    .rv-row {{ display: flex; justify-content: space-between; gap: 10px; font-size: .92rem; }}
    .rv-row span:last-child {{ opacity: .7; white-space: nowrap; }}
    .rv-big {{ font-size: 1.4rem; font-weight: 700; font-variant-numeric: tabular-nums; margin-right: .4rem; }}
    .rv-thin {{ height: 6px; border-radius: 999px; background: {kit.TRACK}; overflow: hidden; margin-top: 4px; }}
    .rv-thin i {{ display: block; height: 100%; background: currentColor; opacity: .6; border-radius: 999px; }}
    .rv-need {{ display: flex; align-items: center; gap: 8px; font-size: .9rem; }}
    .rv-time .rows {{ flex: 1 0 auto; display: flex; flex-direction: column; justify-content: space-evenly; gap: 4px; }}
    .rv-cat {{ display: flex; flex-direction: column; gap: 2px; }}
    .rv-cat .top {{ display: flex; justify-content: space-between; font-size: .9rem; font-variant-numeric: tabular-nums; }}
    .rv-cat .short {{ color: {tones["amber"]}; }} .rv-cat .over {{ color: {tones["good"]}; }}
    .rv-bar {{ position: relative; height: 16px; border-radius: 5px; background: {kit.TRACK}; }}
    .rv-bar > i {{ position: absolute; top: 0; bottom: 0; }}
    .rv-bar .done {{ left: 0; border-radius: 5px 0 0 5px; }}
    .rv-bar .gap {{ background: repeating-linear-gradient(135deg, {kit.rgba(tones["amber"], .55)} 0 3px,
                    {kit.rgba(tones["amber"], .12)} 3px 7px); }}
    .rv-bar .over {{ background: {tones["good"]}; }}
    .rv-bar .tick {{ top: -3px; bottom: -3px; width: 3px; margin-left: -1.5px; border-radius: 2px;
                     background: {kit.ink()}; }}
    .rv-time .foot {{ border-top: 1px solid rgba(128,128,128,.3); padding-top: 8px; display: flex;
                      flex-direction: column; gap: 6px; }}
    .rv-legend {{ display: flex; gap: 14px; align-items: center; font-size: .8rem; opacity: .8; }}
    .rv-legend i {{ display: inline-block; width: 12px; height: 12px; border-radius: 3px; vertical-align: -1px;
                    margin-right: 4px; }}
    </style>""")


def _fill(key):
    """Cards stretch to the column's height on the Review page, not in the pop-up."""
    return "content" if key == POPUP else "stretch"


def _title(text, small=""):
    st.html(f'<div class="rv-h">{escape(text)}' + (f"<small>{escape(small)}</small>" if small else "") + "</div>")


def _verdict(s):
    head = s["headline"]
    word, _, rest = head.partition(": ")
    tone = VERDICT.get(word.split()[0]) if rest else None
    if tone:
        pill, text = _pill(word, tone, big=True), rest[:1].upper() + rest[1:]
    else:
        pill, text = _pill("No verdict yet", "muted", big=True), head
    with st.container(border=True):
        st.html(f'<div>{pill}</div><div class="rv-verdict">{escape(text)}</div>')


def _unconfirmed(s, key):
    days = s["unconfirmed"]
    names = ", ".join(store._as_date(d).strftime("%a") for d in days) if len(days) <= 3 else f"{len(days)} days"
    with st.container(key=f"{key}_nudge", horizontal=True, vertical_alignment="center", gap="small", wrap=False):
        st.html(f'<span class="rv-nudge">⚠ {escape(names)} not confirmed</span>', width="stretch")
        st.button("Confirm", key=f"{key}_confirm", type="primary", on_click=_confirm_days, args=(days, key),
                  help="Their Actual on the Timetable is what you did")
        st.button("Check", key=f"{key}_open", on_click=_open_day, args=(days[0], key),
                  help=f"Open {regional.day_month(store._as_date(days[0]))} on the Timetable")


def _journal(s):
    n = len(s["journal"])
    with st.popover(f"{n} journal entr{'y' if n == 1 else 'ies'} ›", type="tertiary"):
        for e in reversed(s["journal"]):
            st.markdown(f"**{regional.day_month(e['date'])}**  \n{e['text'].strip()}")


def _looking_back(s, key):
    first = s["first"]
    with st.container(border=True, key=f"{key}_back", height=_fill(key)):
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            st.html('<div class="rv-h">Looking back</div>', width="stretch")
            if blocks.is_on("log") and s["journal"]:
                _journal(s)
        if s["promise"]:
            st.markdown(f":gray[:material/flag: Last week you said:] **{s['promise']}**")
            k = f"{key}_kept"
            with st.container(horizontal=True, vertical_alignment="center", gap="small"):
                st.caption("Did you?")
                st.segmented_control("Did you?", list(KEPT.values()), default=KEPT.get(s["review"].get("kept")),
                                     key=k, on_change=_save_kept, args=(first, k), label_visibility="collapsed")
        saved = s["review"]
        tall = None if _fill(key) == "stretch" else 110
        with st.form(f"{key}_reflect", border=False, height=_fill(key)):
            went = st.text_area("What went well?", saved.get("went_well") or "", height=tall)
            change = st.text_area("What will you do differently next week?", saved.get("to_change") or "", height=tall)
            with st.container(horizontal=True, horizontal_alignment="right"):
                if st.form_submit_button("Save", type="primary"):
                    store.save_review(first, went_well=went, to_change=change, seen=True)
                    st.toast("Saved", icon=":material/check_circle:")


def _goal_pace(s, key):
    with st.container(border=True, key=f"{key}_goals"):
        _title("Goal pace")
        if not s.get("goals"):
            st.caption("No goals ran this week.")
            return
        rows = []
        for x in s["goals"]:
            g = x["goal"]
            if x["done"] is not None:
                sub = f"{pace.amount(g, round(x['done'], 1))} this week, needed {pace.amount(g, round(x['need'], 1))}"
            else:
                sub = f"{pace.amount(g, g['value'])} of {pace.amount(g, g['target'])} so far"
            rows.append(f"<div>{_pill(pace.STATES[x['state']], STATE_TONE[x['state']])}"
                        f"<div><b>{escape(g['title'])}</b><div class='m'>{escape(sub)}</div></div></div>")
        st.html(f'<div class="rv-goals">{"".join(rows)}</div>')


def _plan_next_week(first, key):
    from venato.ui import timetable
    timetable._review(first + timedelta(days=7))
    st.session_state["tt_force_mode"] = "plan"
    _whole_app(key)


def _next_week(s, key):
    nxt = s["first"] + timedelta(days=7)
    n = review.next_week(s["first"])
    with st.container(border=True, key=f"{key}_next", height=_fill(key)):
        last = nxt + timedelta(days=6)
        _title("Next week", f"{nxt.day} – {regional.day_month(last, weekday=False)}")
        up = s["deadlines"]["upcoming"]
        dl = "".join(f'<div class="rv-row"><span>{escape(x["title"])}</span>'
                     f'<span>{escape(store.fmt_day(x["due"], "%a %-d"))}</span></div>' for x in up) \
            or '<div class="rv-m">Nothing due.</div>'
        frac = n["frac"] or 0
        planned = (f'<div><span class="rv-big">{_h(n["planned"])} h</span><span class="rv-m">'
                   + (f'of the {_h(n["this_planned"])} h you planned this week' if n["this_planned"]
                      else "planned") + f'</span></div><div class="rv-thin"><i style="width:{100 * frac:.0f}%"></i></div>')
        need = "".join(f'<div class="rv-need">{_pill(g["title"], "bad" if g["state"] == "unreachable" else "amber")}'
                       f'<span>{escape(g["text"])}</span></div>' for g in n["short"]) \
            or '<div class="rv-m">Every goal has its time booked.</div>'
        st.html(f'<div class="rv-next"><section><div class="rv-cap">Deadlines</div>{dl}</section>'
                f'<section><div class="rv-cap">Planned so far</div>{planned}</section>'
                f'<section><div class="rv-cap">Goals that need time booked</div>{need}</section></div>')
        if s.get("sections"):
            with st.expander("From your blocks"):
                for sec in s["sections"]:
                    st.markdown(f"**{sec['title']}**  \n" + "  \n".join(sec["lines"]))
        st.button("Plan next week", key=f"{key}_plan", icon=":material/edit_calendar:", width="stretch",
                  on_click=_plan_next_week, args=(s["first"], key))


def _time(s, key):
    rows = [t for t in s["time"] if t["plan"] or t["actual"]]
    with st.container(border=True, key=f"{key}_time", height=_fill(key)):
        _title("Time", f"planned vs done · {s['days_confirmed']} of 7 confirmed")
        if not rows:
            if store.load_categories().empty:
                from venato.ui import timetable_tools
                timetable_tools.no_categories(f"{key}_addcat", "You have no categories yet, so there's no time to compare.")
            else:
                st.caption("No time on the timetable this week yet.")
            return
        top = 1.03 * max(max(t["plan"], t["actual"]) for t in rows) or 1     # room for a tick at the end
        out = []
        for t in rows:
            plan, done = t["plan"], t["actual"]
            diff = done - plan
            cls, sign = ("short", f" · −{_h(-diff)}") if plan and diff <= -0.5 else \
                ("over", f" · +{_h(diff)}") if plan and diff >= 1 else ("", "")
            pct = lambda h: f"{100 * h / top:.2f}%"          # noqa: E731
            bar = f'<i class="done" style="width:{pct(min(done, plan) if plan else done)};background:{t["colour"]}"></i>'
            if plan and done < plan:
                bar += f'<i class="gap" style="left:{pct(done)};width:{pct(plan - done)}"></i>'
            if plan and done > plan:
                bar += f'<i class="over" style="left:{pct(plan)};width:{pct(done - plan)};border-radius:0 5px 5px 0"></i>'
            if plan:
                bar += f'<i class="tick" style="left:{pct(plan)}"></i>'
            label = f"{_h(done)} of {_h(plan)} h" if plan else f"{_h(done)} h, unplanned"
            out.append(f'<div class="rv-cat"><div class="top"><span>{escape(t["category"])}</span>'
                       f'<span class="{cls}">{label}{sign}</span></div><div class="rv-bar">{bar}</div></div>')
        gaps = review.gaps(s["time"])
        gap_text = ("Gaps: " + ", ".join(f"{g['category']} −{_h(g['plan'] - g['actual'])} h" for g in gaps)) \
            if gaps else "No gaps over an hour."
        amber = kit.amber()
        foot = (f'<div class="foot"><div class="rv-cat"><div class="top"><b>Total</b><span><b>{_h(s["actual_hours"])}'
                f'</b> of {_h(s["planned_hours"])} h</span></div></div>'
                f'<div class="rv-legend"><span><i style="background:{kit.muted()}"></i>Done</span>'
                f'<span><i style="width:3px;background:{kit.ink()}"></i>Target</span>'
                f'<span><i style="background:repeating-linear-gradient(135deg,{kit.rgba(amber, .6)} 0 2px,'
                f'{kit.rgba(amber, .15)} 2px 4px)"></i>Short</span></div>'
                f'<div class="rv-m">{escape(gap_text)}</div></div>')
        st.html(f'<div class="rv-time"><div class="rows">{"".join(out)}</div>{foot}</div>')


def render(first, key, page=False):
    """The review of the week starting `first`, in three columns. `key` keeps widget keys apart (pop-up vs
    page); `page`: the Review page, where the columns fill the window's height."""
    s = review.summary(first)
    _css(key, page)
    with st.container(key=f"{key}_cols", height="stretch" if page else "content"):
        left, mid, right = st.columns([1.08, 1, 1], gap="medium")
        with left:
            _verdict(s)
            if s["unconfirmed"]:
                _unconfirmed(s, key)
            _looking_back(s, key)
        with mid:
            _goal_pace(s, key)
            _next_week(s, key)
        with right:
            _time(s, key)


def trends(first):
    """The last 8 weeks up to `first` as small line charts (the Review page's Trends view)."""
    rows = review.trend(first)
    if sum(r["followed_pct"] is not None or r["actual_hours"] > 0 for r in rows) < 2:
        return                                    # nothing to draw a line through yet
    df = pd.DataFrame(rows)
    df["Week"] = df["week"].map(lambda w: regional.day_month(w, weekday=False))
    charts = [("Plan followed (%)", "followed_pct"), ("Hours logged", "actual_hours")]
    if blocks.is_on("log") and store.tracks_sleep():
        charts += [("Avg sleep (h)", "sleep")]
    charts = [(t, c) for t, c in charts if df[c].notna().sum() >= 2]
    if not charts:
        return
    st.subheader(f"Last {len(rows)} weeks", anchor=False)
    for col, (title, c) in zip(st.columns(len(charts)), charts):
        with col:
            d = df[["Week", c]].dropna().rename(columns={c: title})
            kit.show(kit.line_chart(d, "Week", title, height=140, title=title,
                                    x_axis=alt.Axis(labels=False, title=None)), key=f"rv_trend_{c}")


def regional_accent():
    from venato.ui import appearance
    return appearance.accent()


@st.dialog("Your week", width="large")
def _dialog(first):
    with st.container(horizontal=True, vertical_alignment="center"):
        st.subheader(_week_title(first), anchor=False, width="stretch")
        ask_button(first, POPUP)
    render(first, key=POPUP)
    if st.button("Done", key="review_popup_done", type="primary", icon=":material/check:",
                 help="Close the review; it won't pop up again (it's on the Review page any time)"):
        store.save_review(first, seen=True)
        st.rerun()


def maybe_show():
    """Once per session: the week's review, if it's due (after 7pm Sunday) and not finished with yet.
    It only counts as seen once it's saved or Done is pressed: closed by accident, it comes back next time."""
    if st.session_state.get("review_checked"):
        return
    st.session_state["review_checked"] = True
    week = review.should_show()
    if week:
        _dialog(week)
