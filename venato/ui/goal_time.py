"""
Goals meet the timetable, on screen (the numbers come from venato/pace.py):

  strip(day)        Timetable: a chip per hours goal above the week ("Revision 6/9 h", amber when
                    short; click to fit the rest), the week's budget, Plan my goals, Share hours,
                    and "I'm away" for the week's all-day events
  budget_panel()    Goals page: this week's budget, with the same buttons
  pace_line(p)      Goals page: one goal's pace in a line
  offers()          Goals page: what to do about goals that can't be finished in the time left
  suggestions()     Goals page: "5 h/week of Guitar. Make it a goal?"

Everything works without the assistant: the buttons call the same tools.py functions as Claude.
"""

from datetime import timedelta
from html import escape

import streamlit as st

from venato import pace
from venato import regional
from venato import store
from venato import tools
from venato import undo

PENDING = "goal_time_pending"        # a tools.Pending preview from the Goals page, waiting for Confirm
ICONS = {"done": ":material/check_circle:", "on_track": ":material/check:", "behind": ":material/warning:",
         "slipping": ":material/trending_down:", "unreachable": ":material/error:", "ended": ":material/flag:",
         "upcoming": ":material/schedule:"}
TONE = {"behind": "orange", "slipping": "orange", "unreachable": "red"}


def md(text):
    """Text that shows as itself in st.markdown (titles may contain [ ] * _ and so on)."""
    text = escape(str(text))
    for ch in "\\[]*_`$~":
        text = text.replace(ch, "\\" + ch)
    return text


def _ctx():
    """One pace.Ctx per run of the page (it reads the timetable once)."""
    return pace.Ctx()


# ---------------------------------------------------------------------------
# Timetable: the chip strip above the week
# ---------------------------------------------------------------------------

def _fit_goal(w):
    """Open Fit time for an hours goal's shortfall this week (only free gaps get filled)."""
    from venato.ui import timetable_tools
    g = w["goal"]
    first = max(w["first"], store.local_today())
    timetable_tools.open_fit(g["label"] or g["title"], w["last"], category=g["category"],
                             hours=max(0.5, pace.half_up(w["short"])), first=first)


def strip(day):
    """The goal chips, the week's budget and its buttons (nothing when there are no hours goals or away days)."""
    ctx = _ctx()
    budget = pace.week_budget(day, ctx)
    first = budget["week_start"]
    all_day = [e for e in store.outlook_between(first.isoformat(), (first + timedelta(days=6)).isoformat())
               if e["all_day"]]
    if not budget["goals"] and not all_day and not any(d["away"] for d in budget["days"]):
        return
    row = st.container(horizontal=True, gap="small", vertical_alignment="center", key="tt_goal_strip")
    for w in budget["goals"]:
        g = w["goal"]
        short = w["short"] >= pace.TOLERANCE
        text = f"{g['title']} {pace.fmt(w['covered'])}/{pace.fmt(w['want'])} h"
        help_ = (f"{pace.fmt(w['covered'])} h done or planned of the {pace.fmt(w['want'])} h "
                 f"{g['title']} needs this week ({pace.debt_text(g, w['need'], w['baseline'])}).")
        if short and not w["over"]:
            help_ += f" Click to fit the {pace.fmt(pace.half_up(w['short']))} h short into free time."
        if row.button(f":orange[{text}]" if short else text, key=f"tt_goal_{g['id']}",
                      icon=":material/warning:" if short else ":material/check:", help=help_, type="tertiary"):
            if short and not w["over"]:
                _fit_goal(w)
            else:
                st.toast(f"{g['title']} has enough time planned this week.", icon=":material/check_circle:")
    if budget["goals"]:
        row.markdown(f":{'orange' if budget['over'] else 'gray'}[{md(budget['text'])}]")
        if any(w["short"] >= pace.TOLERANCE and not w["over"] for w in budget["goals"]):
            if row.button("Plan my goals", icon=":material/auto_awesome_motion:", key="tt_plan_goals",
                          help="Fill what each goal is short into free time, top goal first. You'll see it first."):
                from venato.ui import timetable_tools
                timetable_tools.open_plan_goals(first)
        if budget["over"] and row.button("Share hours", icon=":material/balance:", key="tt_split_goals",
                                         help="Goals want more than the week's free time: choose who gets what"):
            split_dialog(first)
    _away_popover(row, first, all_day)


def _away_popover(where, first, events):
    """"I'm away" for any day of the week, or for one of its all-day events: that day then has no free time for goals."""
    away, days_away = store.away_uids(), store.away_days()
    days = [first + timedelta(days=i) for i in range(7)]
    n = len({d.isoformat() for d in days if d.isoformat() in days_away}
            | {e["date"] for e in events if e["uid"] in away})
    with where.popover(f"Away days{f' ({n})' if n else ''}", icon=":material/flight_takeoff:",
                       help="Mark days you're away: they then have no free time for goals."):
        st.caption("Ticked days have no free time for goals.")
        for d in days:
            key = f"tt_away_day_{d.isoformat()}"
            st.checkbox(f"I'm away {regional.day_month(d)}", value=d.isoformat() in days_away, key=key,
                        on_change=lambda day=d, k=key: store.set_away_day(day, st.session_state[k]))
        if events:
            st.caption("Or away for a calendar event (this stays when your calendar syncs):")
        for e in events:
            key = f"tt_away_{e['uid']}"
            st.checkbox(f"I'm away: {e['title']} ({regional.day_month(store._as_date(e['date']))})",
                        value=e["uid"] in away, key=key,
                        on_change=lambda uid=e["uid"], k=key: store.set_away(uid, st.session_state[k]))


@st.dialog("Share this week's time between goals", width="large")
def split_dialog(week):
    """Over budget: which goals are short, and how many hours each gets this week (goal_week)."""
    ctx = _ctx()
    budget = pace.week_budget(week, ctx)
    first = budget["week_start"]
    st.caption(f"{budget['text']} Higher goals in your list get time first; change the hours to share it "
               "your way. Hours = done so far plus what to plan for the rest of the week.")
    hours = {}
    for w in budget["goals"]:
        g = w["goal"]
        a, b = st.columns([3, 2], vertical_alignment="center")
        note = (f":orange[short by {pace.fmt(w['budget_short'])} h]" if w["budget_short"] > pace.TOLERANCE
                else ":gray[fits]")
        a.markdown(f"**{md(g['title'])}** · wants {pace.fmt(w['want'])} h · {note}")
        default = w["chosen"] if w["chosen"] is not None else w["done"] + w["alloc"]
        hours[g["id"]] = b.number_input(f"Hours for {g['title']}", 0.0, 168.0, float(round(default * 2) / 2),
                                        step=0.5, key=f"split_{first}_{g['id']}", label_visibility="collapsed")
    planned = sum(max(0.0, hours[w["goal"]["id"]] - w["done"]) for w in budget["goals"])
    st.markdown(f"Planned for the rest of the week: **{pace.fmt(planned)} h** of {pace.fmt(budget['capacity'])} h free"
                + (" · :orange[more than you have]" if planned > budget["capacity"] + pace.TOLERANCE else ""))
    a, b, _ = st.columns([1, 1.4, 2])
    if a.button("Save", type="primary", key="split_save"):
        undo.checkpoint("Changed how this week's time is shared between goals")
        store.set_goal_week_hours(first, hours)
        st.rerun()
    if b.button("Back to automatic", key="split_auto"):
        undo.checkpoint("Went back to sharing this week's time automatically")
        store.set_goal_week_hours(first, {})
        st.rerun()


# ---------------------------------------------------------------------------
# Goals page
# ---------------------------------------------------------------------------

def pace_line(p):
    """One goal's pace under its bar."""
    tone = TONE.get(p["state"])
    text = md(p["line"])
    st.markdown(f"{ICONS[p['state']]} " + (f":{tone}[{text}]" if tone else f":gray[{text}]"))


def _confirm_box():
    """A waiting preview (a negotiation offer) with Confirm / Cancel; True while one is waiting."""
    pending = st.session_state.get(PENDING)
    if not pending:
        return False
    with st.container(border=True):
        st.warning(pending.summary, icon=":material/preview:")
        a, b, _ = st.columns([1, 1, 3])
        if a.button("Confirm", type="primary", key="goal_offer_yes"):
            undo.checkpoint(pending.summary)
            r = pending.run()
            st.session_state.pop(PENDING, None)
            st.toast(r.text, icon=":material/check_circle:")
            st.rerun()
        if b.button("Cancel", key="goal_offer_no"):
            st.session_state.pop(PENDING, None)
            st.rerun()
    return True


def _offer(goal_id, kind):
    r = tools.resolve_goal(goal_id, kind)
    if r.pending:
        st.session_state[PENDING] = r.pending
    else:
        st.toast(r.text)


def budget_panel(ctx=None):
    """This week's budget for hours goals, with Plan my goals / Share hours."""
    ctx = ctx or _ctx()
    budget = pace.week_budget(ctx.today, ctx)
    if not budget["goals"]:
        return
    with st.container(border=True):
        st.subheader("This week's time", anchor=False)
        st.markdown((":orange[" if budget["over"] else "") + md(budget["text"]) + ("]" if budget["over"] else ""))
        for w in budget["goals"]:
            g = w["goal"]
            gap = f" · :orange[{pace.fmt(w['short'])} h short]" if w["short"] >= pace.TOLERANCE else ""
            st.markdown(f"**{md(g['title'])}** {pace.fmt(w['covered'])}/{pace.fmt(w['want'])} h{gap}  \n"
                        f":gray[{md(pace.debt_text(g, w['need'], w['baseline']))}]")
        row = st.container(horizontal=True, gap="small")
        if any(w["short"] >= pace.TOLERANCE for w in budget["goals"]):
            if row.button("Plan my goals", icon=":material/auto_awesome_motion:", key="goals_plan",
                          help="Fill what each goal is short into free time this week, top goal first."):
                from venato.ui import timetable_tools
                timetable_tools.open_plan_goals(budget["week_start"])
        if row.button("Share hours", icon=":material/balance:", key="goals_split",
                      help="Choose how this week's free time is shared between goals"):
            split_dialog(budget["week_start"])


def offers(ctx=None):
    """Cards for goals that can't be finished with the time (or days) left: lower, carry or take hours."""
    ctx = ctx or _ctx()
    if _confirm_box():
        return
    gone = pace.dismissed_offers()
    for period in store.GOAL_PERIODS:
        for g in store.goals_in(period, ctx.today):
            if g["id"] in gone:
                continue
            n = pace.negotiation(g, ctx)
            if not n:
                continue
            with st.container(border=True):
                p = n["pace"]
                st.markdown(f":material/error: **{md(g['title'])}** can't be finished in time: "
                            f"{md(pace.amount(g, p['remaining']))} to go, about "
                            f"{md(pace.amount(g, n['reachable'] - p['value']))} within reach.")
                row = st.container(horizontal=True, gap="small")
                for o in n["offers"]:
                    row.button(o["text"], key=f"offer_{o['kind']}_{g['id']}", on_click=_offer, args=(g["id"], o["kind"]))
                row.button("Not now", key=f"offer_no_{g['id']}", type="tertiary", on_click=pace.dismiss_offer,
                           args=(g["id"],), help="Hide this for this goal")


def _accept(s, target):
    tools.add_goal(s["label"] or s["category"], target, period="monthly", unit="h", category=s["category_id"],
                   label=s["label"])


def suggestions(ctx=None):
    """'5 h/week of Guitar. Make it a goal?' cards (dismissals are remembered)."""
    ctx = ctx or _ctx()
    for s in pace.suggestions(ctx):
        target = pace.suggested_target(s["per_week"], ctx.today)
        with st.container(border=True):
            st.markdown(f":material/lightbulb: {md(s['text'])}  \n"
                        f":gray[A goal of {target} h this month, counted from your timetable's Actual hours.]")
            row = st.container(horizontal=True, gap="small")
            row.button("Make it a goal", key=f"suggest_yes_{s['key']}", icon=":material/add:",
                       on_click=_accept, args=(s, target))
            row.button("No thanks", key=f"suggest_no_{s['key']}", type="tertiary",
                       on_click=pace.dismiss_suggestion, args=(s,))
