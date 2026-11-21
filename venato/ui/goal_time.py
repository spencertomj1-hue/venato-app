"""
Goals meet the timetable, on screen (the numbers come from venato/pace.py):

  planner(first)    Timetable: the "Plan this week" panel beside the grid: free hours per day, each
                    hours goal's week as a bar with "Fit N h", Plan all goals, Share hours, I'm away
  suggestion_bar()  Timetable: "4 suggested sittings fill 7.5 h" with Add all to Plan / Dismiss, and the
                    Show suggestions toggle; suggestions_for() gives the grid its dashed sittings
  free_split()      Goals page: "Where this week's N h free go", a stacked bar by goal, with Plan my goals
  pace_line(p)      Goals page: one goal's pace in a line
  offers()          Goals page: what to do about goals that can't be finished in the time left
  suggestions()     Goals page: "5 h/week of Guitar. Make it a goal?"

Everything works without the assistant: the buttons call the same tools functions as Claude.
"""

from datetime import timedelta
from html import escape

import streamlit as st

from venato import feedback
from venato import pace
from venato import regional
from venato import store
from venato import tools
from venato import undo
from venato.ui import kit

PENDING = "goal_time_pending"        # a tools.Pending preview from the Goals page, waiting for Confirm
ICONS = {"done": ":material/check_circle:", "on_track": ":material/check:", "behind": ":material/warning:",
         "slipping": ":material/trending_down:", "unreachable": ":material/error:", "ended": ":material/flag:",
         "upcoming": ":material/schedule:"}
TONE = {"behind": "orange", "slipping": "orange", "unreachable": "red"}


md = kit.md                    # text that shows as itself in st.markdown


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


# ---------------------------------------------------------------------------
# Timetable: suggested sittings (drawn dashed in the grid's free gaps)
# ---------------------------------------------------------------------------

def show_suggestions():
    """Settings: "show_suggestions" (default on): the grid draws where Plan my goals would put time."""
    return bool(store.load_settings().get("show_suggestions", True))


def _dismissed_weeks():
    return set(store.load_settings().get("suggestions_dismissed") or [])


def suggestions_for(first, ctx=None):
    """
    The sittings Plan my goals would add in the week starting `first`, for the grid:
    [{"id", "date", "start", "end", "label", "categoryId", "goal"}] (empty when switched off, dismissed
    for that week, or nothing is short). Computed by tools.goal_spots: free gaps from now on only.
    """
    if not show_suggestions() or first.isoformat() in _dismissed_weeks():
        return []
    try:
        placed = tools.goal_spots(first.isoformat(), ctx=ctx)
    except tools.ToolError:
        return []
    return [{"id": f"sg:{d}:{store.slot_time(a)}", "date": d, "start": store.slot_time(a), "end": store.slot_time(b),
             "label": g["label"] or g["title"], "categoryId": g["category_id"], "goal": g["title"]}
            for g, spots in placed for d, a, b in spots]


def add_suggestion(date, start, end, block, new_id=None):
    """One suggested sitting clicked in the grid: painted in only if those slots are still free (into the
    Plan, or today's Actual once the day has started and its Plan is locked)."""
    s, e = store.slot_of(start), store.slot_of(end)
    if not any(a <= s and e <= b for a, b in store.free_runs(date, s, e)):
        return False                                  # something's there now: never overwrite it
    store.paint(date, store.live_track(date), s, e, block, new_id=new_id)
    return True


def _toggle_suggestions():
    store.save_settings(show_suggestions=bool(st.session_state.get("tt_show_sugg")))


def _dismiss_week(first):
    store.save_settings(suggestions_dismissed=sorted(_dismissed_weeks() | {first.isoformat()})[-20:])


def _undismiss_week(first):
    store.save_settings(suggestions_dismissed=sorted(_dismissed_weeks() - {first.isoformat()}))


def suggestion_bar(first, sugg, ctx=None, row=None):
    """Above the grid: what the suggested sittings add up to, Add all to Plan, Dismiss, and the toggle
    (into `row` if given, so it shares the toolbar's line)."""
    ctx = ctx or _ctx()
    if not pace.week_goals(first, ctx):
        return                                                    # no hours goals that week: nothing to suggest
    row = row or st.container(horizontal=True, gap="small", vertical_alignment="center", key="tt_sugg_bar")
    if sugg:
        hours = sum(store.slot_of(x["end"]) - store.slot_of(x["start"]) for x in sugg) / 2
        n = len(sugg)
        row.markdown(f":material/lightbulb: {n} suggested sitting{'s' if n > 1 else ''} fill **{pace.fmt(hours)} h**",
                     width="content",
                     help="They go in free time; nothing already there moves. Click one to add just that sitting.")
        if row.button("Add all to Plan", icon=":material/playlist_add:", key="tt_sugg_all", type="primary",
                      help="Plan my goals: adds every suggested sitting, with a preview first"):
            from venato.ui import timetable_tools
            timetable_tools.open_plan_goals(first)
        row.button("Dismiss", key="tt_sugg_dismiss", type="tertiary", on_click=_dismiss_week, args=(first,),
                   help="Hide the suggestions for this week")
    elif show_suggestions() and first.isoformat() in _dismissed_weeks():
        row.button("Show this week's suggestions again", key="tt_sugg_back", type="tertiary",
                   on_click=_undismiss_week, args=(first,))
    row.toggle("Show suggestions", value=show_suggestions(), key="tt_show_sugg", on_change=_toggle_suggestions,
               help="Draw where your goals' missing hours would fit, as dashed sittings in free time")


# ---------------------------------------------------------------------------
# Timetable: the "Plan this week" panel beside the grid
# ---------------------------------------------------------------------------

def _free_bars(days):
    """Free hours for goals per day as small bars (away days at zero, labelled), with a text equivalent."""
    top = max(1.0, store.SLOTS / 2)
    cols, said = [], []
    for d in days:
        day = store._as_date(d["date"])
        name = regional.day_month(day)
        what = "away" if d["away"] else "over" if d["past"] else f"{pace.fmt(d['hours'])} h" + ("≈" if d["estimate"] else "")
        said.append(f"{name}: {what}")
        h = 0 if d["away"] or d["past"] else d["hours"]
        cols.append(f'<div class="fb-col"><div class="fb-bar"><i style="height:{100 * h / top:.1f}%"></i></div>'
                    f'<b>{escape(pace.fmt(h) if not d["away"] else "away")}</b><span>{escape(f"{day:%a}"[0])}</span></div>')
    from venato.ui import appearance
    return f"""<style>
      .fb {{ display: grid; grid-template-columns: repeat(7, 1fr); gap: 6px; align-items: end; }}
      .fb-col {{ display: flex; flex-direction: column; align-items: center; gap: 2px; font-size: 0.72rem; }}
      .fb-col b {{ font-weight: 600; font-variant-numeric: tabular-nums; }}
      .fb-col span {{ opacity: 0.78; }}
      .fb-bar {{ position: relative; width: 100%; height: 56px; border-radius: 4px; background: rgba(128,128,128,0.16);
                 display: flex; align-items: flex-end; overflow: hidden; }}
      .fb-bar i {{ display: block; width: 100%; background: {appearance.accent()}; opacity: 0.75; }}
    </style><div class="fb" role="img" aria-label="{escape('Free hours for goals: ' + '; '.join(said))}">{''.join(cols)}</div>"""


def planner(first, ctx=None):
    """The "Plan this week" panel (Timetable B): free hours per day, each hours goal's bar with Fit N h,
    Plan all goals, Share hours when the week is over budget, and I'm away for each day."""
    ctx = ctx or _ctx()
    budget = pace.week_budget(first, ctx)
    first = budget["week_start"]
    ended = first + timedelta(days=6) < ctx.today            # a past week: a scorecard, nothing to plan
    confirmed, so_far = ctx.confirmed(first, first + timedelta(days=6))
    with st.container(border=True, key="tt_planner"):
        kit.subhead("How the week went" if ended else "Plan this week")
        st.caption(f"Free hours for goals per day · {pace.fmt(budget['capacity'])} h in all")
        st.html(_free_bars(budget["days"]))
        rows = [w for w in budget["goals"]]
        if rows:
            st.html(bar_style(legend=not all(w["over"] for w in rows)))   # (a past week: just "done of")
            for w in rows:
                g = w["goal"]
                st.html(_score(w, confirmed == so_far) if w["over"] else _bar(w))
                if w["short"] >= pace.TOLERANCE and not w["over"]:
                    if st.button(f"Fit {pace.fmt(pace.half_up(w['short']))} h", key=f"tt_fit_goal_{g['id']}",
                                 icon=":material/event_available:",
                                 help=f"Fit time for {g['title']}, filled in with what it's short this week"):
                        _fit_goal(w)
            if any(w["short"] >= pace.TOLERANCE and not w["over"] for w in rows):
                if st.button("Plan all goals", icon=":material/auto_awesome_motion:", key="tt_plan_goals",
                             type="primary", width="stretch",
                             help="Fill what each goal is short into free time, top goal first. You'll see it first."):
                    from venato.ui import timetable_tools
                    timetable_tools.open_plan_goals(first)
            if budget["over"] and not ended and st.button("Share hours", icon=":material/balance:", key="tt_split_goals",
                                            width="stretch",
                                            help="Goals want more than the week's free time: choose who gets what"):
                split_dialog(first)
            if so_far and confirmed < so_far:
                n = so_far - confirmed
                st.caption(f":material/pending: {n} day{'s' if n != 1 else ''} not confirmed: confirm "
                           f"{'them' if n != 1 else 'it'} to count {'their' if n != 1 else 'its'} hours.")
        all_day = [e for e in store.outlook_between(first.isoformat(), (first + timedelta(days=6)).isoformat())
                   if e["all_day"]]
        _away_boxes(first, all_day)


def _away_boxes(first, events):
    """"I'm away" for each day of the week, or for one of its all-day events: that day then has no free time for goals."""
    away, days_away = store.away_uids(), store.away_days()
    st.caption("Ticked days have no free time for goals.")
    for i in range(7):
        d = first + timedelta(days=i)
        key = f"tt_away_day_{d.isoformat()}"
        st.checkbox(f"I'm away {regional.day_month(d)}", value=d.isoformat() in days_away, key=key,
                    on_change=lambda day=d, k=key: store.set_away_day(day, st.session_state[k]))
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

BADGE = {"done": "green", "on_track": "green", "behind": "orange", "slipping": "orange", "unreachable": "red",
         "ended": "gray", "upcoming": "gray"}


def badge(state):
    """The state as a small coloured badge with an icon (so it's never colour alone)."""
    return f":{BADGE[state]}-badge[{ICONS[state]} {pace.STATES[state]}]"


def pace_line(p):
    """One goal's pace under its bar: a state badge, then the details in muted text."""
    st.markdown(badge(p["state"]))
    if p.get("details"):
        st.caption("  \n".join(md(d) for d in p["details"]))


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


def _bar(w):
    """One goal's week as a bar: done (solid), planned (light), the rest of what it wants (track),
    and the part of the need carried over from earlier weeks (hatched). Text is never colour alone."""
    g = w["goal"]
    want, done, planned = w["want"], w["done"], w["planned_future"]
    scale = max(want, done + planned, 0.01)
    pct = lambda x: f"{100 * max(0.0, min(x, scale)) / scale:.2f}%"
    carried = max(0.0, w["need"] - w["baseline"]) * w["factor"]
    short = w["short"]
    f = pace.fmt
    label = (f"{g['title']}: {f(done)} h done and {f(planned)} h planned of {f(want)} h this week"
             + (f", including {f(carried)} h carried over" if carried >= 0.05 else "")
             + (f", {f(short)} h short" if short >= pace.TOLERANCE else ""))
    hatch = (f'<i class="wb-carry" style="left:{pct(want - carried)};width:{pct(carried)}" '
             f'title="{f(carried)} h carried over from earlier weeks"></i>') if carried >= 0.05 else ""
    tick = f'<i class="wb-tick" style="left:{pct(want)}" title="Wants {f(want)} h"></i>' if done + planned > want else ""
    note = [pace.week_text(g, w["need"], w["baseline"])]
    if w["factor"] > 1 and want > done:
        note.append(f"plans {f(want - done)} h to land {f(max(0.0, w['need'] - done))} h")
    status = (f'<span class="wb-short">⚠ {f(short)} h short</span>' if short >= pace.TOLERANCE
              else '<span class="wb-ok">✓ covered</span>')
    return f"""<div class="wb-row" role="img" aria-label="{escape(label)}">
      <div class="wb-top"><b>{escape(g['title'])}</b>
        <span class="wb-num">{f(done + planned)} / {f(want)} h</span>{status}</div>
      <div class="wb-track">
        <i class="wb-done" style="width:{pct(done)}" title="{f(done)} h done"></i>
        <i class="wb-plan" style="width:{pct(planned)}" title="{f(planned)} h planned"></i>
        <i class="wb-rest" title="{f(max(0.0, want - done - planned))} h not planned yet"></i>
        {hatch}{tick}
      </div>
      <div class="wb-note">{escape(' · '.join(note))}</div>
    </div>"""


def _score(w, all_confirmed):
    """A week that's over, for one goal: done of what it needed that week, as a bar and in words. "Missed"
    only when every day is confirmed; otherwise it's short *on the confirmed days* (the rest may count yet)."""
    g = w["goal"]
    f = pace.fmt
    done, need = w["done"], w["need"]
    scale = max(need, done, 0.01)
    pct = lambda x: f"{100 * max(0.0, min(x, scale)) / scale:.2f}%"
    gap = need - done
    if gap < pace.TOLERANCE:
        status, words = '<span class="wb-ok">✓ hit</span>', "hit"
    elif all_confirmed:
        status, words = f'<span class="wb-short">✕ missed by {f(gap)} h</span>', f"missed by {f(gap)} h"
    else:
        status, words = (f'<span class="wb-short">⚠ {f(gap)} h short so far</span>',
                         f"{f(gap)} h short on the days confirmed so far")
    label = f"{g['title']}: {f(done)} h done of the {f(need)} h it needed that week, {words}"
    return f"""<div class="wb-row" role="img" aria-label="{escape(label)}">
      <div class="wb-top"><b>{escape(g['title'])}</b>
        <span class="wb-num">done {f(done)} of {f(need)} h</span></div>
      <div class="wb-track">
        <i class="wb-done" style="width:{pct(done)}" title="{f(done)} h done"></i>
        <i class="wb-rest" title="{f(max(0.0, need - done))} h not done"></i>
      </div>
      <div class="wb-note">{status}</div>
    </div>"""


def bar_style(legend=True):
    """The CSS for _bar (once per page) and the one legend: Done / Planned / Not planned yet / Carried over."""
    from venato.ui import appearance
    dark = appearance.is_dark()
    accent = appearance.accent()
    warn = "#FBBF24" if dark else "#B45309"
    ok = "#4ADE80" if dark else "#146C2E"
    return f"""<style>
      .wb {{ display: grid; gap: 14px; margin: 2px 0 4px; }}
      .wb-legend {{ display: flex; gap: 16px; font-size: 0.78rem; opacity: 0.8; flex-wrap: wrap; }}
      .wb-legend span {{ display: inline-flex; align-items: center; gap: 6px; }}
      .wb-key {{ width: 14px; height: 8px; border-radius: 4px; display: inline-block; }}
      .wb-top {{ display: flex; align-items: baseline; gap: 10px; font-size: 0.92rem; margin-bottom: 5px; }}
      .wb-num {{ margin-left: auto; font-variant-numeric: tabular-nums; opacity: 0.8; }}
      .wb-short {{ color: {warn}; font-size: 0.82rem; font-weight: 600; white-space: nowrap; }}
      .wb-ok {{ color: {ok}; font-size: 0.82rem; font-weight: 600; white-space: nowrap; }}
      .wb-track {{ position: relative; display: flex; gap: 2px; height: 10px; }}
      .wb-track > i {{ display: block; height: 100%; border-radius: 4px; flex: none; }}
      .wb-track > i[style*="width:0.00%"] {{ display: none; }}
      .wb-done {{ background: {accent}; }}
      .wb-plan {{ background: {accent}; opacity: 0.4; }}
      .wb-rest {{ flex: 1 1 auto !important; background: rgba(128,128,128,0.18); }}
      .wb-carry {{ position: absolute; top: 0; bottom: 0; border-radius: 4px; pointer-events: auto;
                   background: repeating-linear-gradient(45deg, transparent 0 3px, rgba(128,128,128,0.55) 3px 4.5px); }}
      .wb-tick {{ position: absolute; top: -3px; bottom: -3px; width: 2px; margin-left: -1px; background: currentColor; opacity: 0.7; }}
      .wb-note {{ font-size: 0.8rem; opacity: 0.78; margin-top: 4px; }}
      .wb-legend .wb-carry-key {{ background: repeating-linear-gradient(45deg, transparent 0 3px, rgba(128,128,128,0.7) 3px 4.5px);
                                 border: 1px solid rgba(128,128,128,0.4); }}
      .wb-row {{ margin: 2px 0 2px; }}
    </style>
      """ + ("" if not legend else f"""      <div class="wb-legend" aria-hidden="true">
        <span><i class="wb-key" style="background:{accent}"></i>Done</span>
        <span><i class="wb-key" style="background:{accent};opacity:0.4"></i>Planned</span>
        <span><i class="wb-key" style="background:rgba(128,128,128,0.18)"></i>Not planned yet</span>
        <span><i class="wb-key wb-carry-key"></i>Carried over</span>
      </div>""")


# Categorical colours for goals in the free-time bar (validated with the dataviz skill's checker: lightness band,
# colour-blind separation of neighbours, 3:1 in dark; light mode relies on the legend's names and hours).
GOAL_COLOURS = {"light": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#6250d6"],
                "dark": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#9085e9"]}


def goal_colour(i):
    """A goal's colour by its place in the week's list (a 7th and later goal share the last one's)."""
    from venato.ui import appearance
    ramp = GOAL_COLOURS["dark" if appearance.is_dark() else "light"]
    return ramp[min(i, len(ramp) - 1)]


def free_split(ctx=None):
    """
    Goals page: "Where this week's N h free go": one stacked bar of the rest of the week's free time,
    split by what each hours goal gets (its alloc, top goal first) and Unclaimed, with a legend that
    names each part and its hours, Plan my goals, and Share hours when goals want more than there is.
    """
    ctx = ctx or _ctx()
    budget = pace.week_budget(ctx.today, ctx)
    if not budget["goals"]:
        return
    cap = budget["capacity"]
    parts = [(w["goal"]["title"], w["alloc"], goal_colour(i)) for i, w in enumerate(budget["goals"])]
    unclaimed = max(0.0, cap - sum(h for _, h, _ in parts))
    f = pace.fmt
    total = max(cap, 0.01)
    segs = "".join(f'<i style="flex:{h / total:.4f} 1 0;background:{c}" title="{escape(t)}: {f(h)} h"></i>'
                   for t, h, c in parts if h >= 0.05)
    if unclaimed >= 0.05 or not segs:
        segs += f'<i class="fs-free" style="flex:{max(unclaimed, 0.01) / total:.4f} 1 0" title="Unclaimed: {f(unclaimed)} h"></i>'
    keys = "".join(f'<li><i style="background:{c}"></i><span>{escape(t)}</span><b>{f(h)} h</b></li>' for t, h, c in parts)
    keys += f'<li class="fs-u"><i class="fs-free"></i><span>Unclaimed</span><b>{f(unclaimed)} h</b></li>'
    label = (f"{f(cap)} hours free for goals this week: " + ", ".join(f"{t} {f(h)} h" for t, h, _ in parts)
             + f", {f(unclaimed)} h unclaimed")
    with st.container(border=True, key="goals_free_split"):
        st.subheader(f"Where this week's {f(cap)} h free go", anchor=False)
        st.html(f"""<style>
          .fs-bar {{ display: flex; gap: 2px; height: 14px; margin: 2px 0 10px; }}
          .fs-bar i {{ display: block; border-radius: 4px; min-width: 4px; }}
          .fs-free {{ background: rgba(128,128,128,0.2); border: 1px solid rgba(128,128,128,0.45); box-sizing: border-box; }}
          .fs-keys {{ list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; font-size: 0.9rem; }}
          .fs-keys li {{ display: flex; align-items: center; gap: 8px; }}
          .fs-keys li i {{ width: 10px; height: 10px; border-radius: 3px; flex: none; display: inline-block; }}
          .fs-keys b {{ margin-left: auto; font-weight: 600; font-variant-numeric: tabular-nums; }}
          .fs-keys .fs-u span {{ opacity: 0.85; }}
        </style><div class="fs-bar" role="img" aria-label="{escape(label)}">{segs}</div><ul class="fs-keys">{keys}</ul>""")
        if budget["over"]:
            st.caption(":material/warning: " + md(budget["text"]))
        row = st.container(horizontal=True, gap="small")
        if any(w["short"] >= pace.TOLERANCE and not w["over"] for w in budget["goals"]):
            if row.button("Plan my goals", icon=":material/auto_awesome_motion:", key="goals_plan",
                          help="Fill what each goal is short into free time this week, top goal first."):
                from venato.ui import timetable_tools
                timetable_tools.open_plan_goals(budget["week_start"])
        if row.button("Share hours", icon=":material/balance:", key="goals_split",
                      help="Choose how this week's free time is shared between goals"):
            split_dialog(budget["week_start"])


# ---------------------------------------------------------------------------
# Home: "Needs you"
# ---------------------------------------------------------------------------

PILL = {"behind": "orange", "slipping": "orange", "unreachable": "red"}
NEW_GOAL_DAYS = 7               # a goal this young isn't "behind": it just needs time planned for it
NEEDS_PLAN = ":blue-badge[:material/edit_calendar: Needs a plan]"
EMPTY = "Nothing needs you. Go touch grass."
DEADLINE_DAYS = 7               # deadlines this soon need a plan
OFFER_AFTER_DAYS = 7            # the assistant is offered (once) this long after first using Venato


def deadline_needs_plan(d, ctx):
    """Why a deadline due within the week needs you, or "" when it doesn't: no plan yet, or behind on its plan
    (a deadline's plan is an hours goal, so "behind" is the goal's own pace)."""
    goal = store.deadline_goal(d["id"])
    if not goal:
        return "no plan yet"
    return "behind on its plan" if pace.goal_pace(goal, ctx)["state"] in PILL else ""


def _goal_rows(ctx):
    """[(pace, state, what it needs)] for goals (not a deadline's plan: its deadline row says it) behind (or slipping, or out of reach) or short of time this week."""
    rows = []
    for p in pace.pace_all(ctx):
        g, w = p["goal"], p.get("week")
        if g.get("deadline_id"):
            continue                       # a deadline's plan shows once, as its deadline row
        short = w["short"] if w and not w["over"] else 0.0
        if p["state"] not in PILL and short < pace.TOLERANCE:
            continue
        state = p["state"] if p["state"] in PILL else "behind"
        if state == "behind" and _just_started(p, ctx.today):
            state = "needs_plan"
        what = (f"{pace.fmt(pace.half_up(short))} h to plan" if short >= pace.TOLERANCE
                else f"{pace.amount(g, p['need'])} this week" if p["need"] else "")
        rows.append((p, state, what))
    return rows


def _just_started(p, today):
    """An hours goal in its first week with nothing done: "behind" would only mean no time is planned yet."""
    return (p["goal"]["kind"] == "hours" and p["value"] < pace.TOLERANCE
            and (today - p["start"]).days < NEW_GOAL_DAYS)


def _deadline_rows(ctx):
    """[(deadline, why)] due in the next week that have no plan or are behind on it."""
    last = ctx.today + timedelta(days=DEADLINE_DAYS)
    out = []
    for d in store.deadlines():
        if ctx.today <= store._as_date(d["due"]) <= last:
            why = deadline_needs_plan(d, ctx)
            if why:
                out.append((d, why))
    return out


def _past_days():
    """Today (once its Plan is over) and yesterday, if not confirmed (timetable.prompt_days); not an empty day
    from before you started using Venato."""
    from venato.ui import timetable
    first = store.load_settings().get("first_seen") or ""
    out = []
    for day in timetable.prompt_days():
        iso = day.isoformat()
        if iso < first and not (store.blocks_between(iso, iso) or store.outlook_between(iso, iso)):
            continue
        out.append(day)
    return out


def assistant_offer_due(today=None):
    """The one-time "try the assistant" card: a week after first using Venato, while the assistant is off,
    until it's been answered."""
    s = store.load_settings()
    if store.ai_enabled() or s.get("assistant_offer_done") or not s.get("first_seen"):
        return False
    try:
        first = store._as_date(s["first_seen"])
    except (TypeError, ValueError):
        return False
    return ((today or store.local_today()) - first).days >= OFFER_AFTER_DAYS


def needs_items(ctx=None):
    """Everything that needs you now: unconfirmed days, goals, deadlines, the blocks' own items and the
    assistant card. Parts whose block is off are empty."""
    from venato import blocks
    ctx = ctx or _ctx()
    goals_on = blocks.is_on("goals")
    return {"days": _past_days() if blocks.is_on("timetable") else [],
            "goals": _goal_rows(ctx) if goals_on else [],
            "deadlines": _deadline_rows(ctx) if goals_on else [],
            "blocks": blocks.needs(),
            "assistant": assistant_offer_due(ctx.today),
            "feedback": feedback.card_due(ctx.today)}


def _open_page(page):
    st.session_state["page"] = page


def _assistant_answer(open_settings):
    store.save_settings(assistant_offer_done=True)
    if open_settings:
        st.session_state["settings_tab"] = "claude"
        st.session_state["page"] = "Settings"


TILE_LIMIT = 3          # Home's Needs you tile: this many things, then "+N more"


def needs_you(ctx=None, limit=None, heading=True):
    """
    Everything that wants something from you, in one card:
      - today (once its Plan is over) and yesterday if unconfirmed: Confirm / Review / Not now
      - goals behind (or slipping, or out of reach) or short of time this week, each with its state pill,
        "N h to plan", its bar with the "should be here by today" tick, and Plan my goals
      - deadlines in the next 7 days with no plan (or behind on it)
      - the blocks' own items (Block.needs)
      - once, a week in, with the assistant off: where to switch it on
      - once, two weeks in: "How's Venato treating you?" with a link to the feedback form
    Nothing: "Nothing needs you. Go touch grass."
    limit (Home's tile): only the first `limit` things, each on one line (goals without their bar), then
    "+N more" (a tap on the tile opens this card in full, in a dialog). Without it, all of them.
    """
    ctx = ctx or _ctx()
    items = needs_items(ctx)
    tile = limit is not None
    rows = ([("day", d) for d in items["days"]] + [("goal", r) for r in items["goals"]]
            + [("deadline", r) for r in items["deadlines"]] + [("block", (i, r)) for i, r in enumerate(items["blocks"])]
            + [("assistant", None)] * bool(items["assistant"]) + [("feedback", None)] * bool(items["feedback"]))
    shown = rows[:limit] if tile else rows
    pre = "" if tile else "all_"                  # the dialog draws next to the tile: its own keys
    with st.container(border=True, key="home_needs_you" if tile else "needs_you_all"):
        if heading:
            kit.subhead("Needs you")
        if not rows:
            st.markdown(EMPTY)
            return
        goals_shown = [r for kind, r in shown if kind == "goal"]
        hidden = len(rows) - len(shown)
        for n, (kind, r) in enumerate(shown):
            if tile and hidden and n == len(shown) - 1:      # the last one shares its line with "+N more"
                line = st.container(horizontal=True, vertical_alignment="center", gap="small")
                box = line.container(width="stretch")
                line.caption(f"+{hidden} more", width="content")
                with box:
                    _needs_row(kind, r, ctx, pre, tile, goals_shown)
            else:
                _needs_row(kind, r, ctx, pre, tile, goals_shown)


def _needs_row(kind, r, ctx, pre, tile, goals_shown):
    """One thing in Needs you (see needs_you). Goals in full are drawn together, at the first one."""
    if kind == "day":
        from venato.ui import timetable
        timetable.end_of_day_row(r, prefix=pre, compact=tile)
    elif kind == "goal" and tile:
        _goal_line(r)
    elif kind == "goal" and r is goals_shown[0]:
        _needs_goals(goals_shown, ctx)
    elif kind == "deadline":
        d, why = r
        when = store.countdown(d["due"], ctx.today, d.get("due_time"), store.local_now())
        st.markdown(f":material/event: **{md(d['title'])}** · {md(when)} · :gray[{md(why)}]")
    elif kind == "block":
        i, item = r
        row = st.container(horizontal=True, vertical_alignment="center", gap="small")
        row.markdown(f"{item['icon'] or ''} {md(item['text'])}".strip(), width="stretch")
        if item.get("page"):
            row.button("Open", key=f"{pre}needs_open_{i}_{item['block']}", type="tertiary",
                       icon=":material/arrow_forward:", on_click=_open_page, args=(item["page"],))
    elif kind == "assistant":
        _assistant_card(pre, tile)
    elif kind == "feedback":
        _feedback_card(pre, tile)


def _goal_line(r):
    """A goal in Home's tile: its pill, its name and what it needs, on one line."""
    p, state, what = r
    pill = NEEDS_PLAN if state == "needs_plan" else f":{PILL[state]}-badge[{ICONS[state]} {pace.STATES[state]}]"
    st.markdown(f"{pill} **{md(p['goal']['title'])}**" + (f" · {md(what)}" if what else ""))


def _card_row(text, tile):
    """The row a card's buttons go in: beside its text in the tile (one line), under it in full."""
    if not tile:
        st.markdown(text)
    row = st.container(horizontal=True, gap="small", vertical_alignment="center")
    if tile:
        row.markdown(text, width="stretch")
    return row


def _assistant_card(pre, tile):
    text = (":material/chat: **Want a hand?** Turn it on in Settings → Assistant." if tile else
            ":material/chat: **Want a hand?** The assistant can plan your week with you and answer "
            "questions about your notes. Turn it on in Settings → Assistant.")
    row = _card_row(text, tile)
    row.button("Open Settings", key=f"{pre}needs_ai_yes", icon=":material/settings:",
               on_click=_assistant_answer, args=(True,))
    row.button("No thanks", key=f"{pre}needs_ai_no", type="tertiary", on_click=_assistant_answer, args=(False,),
               help="Hide this for good. The assistant stays in Settings if you change your mind.")


def _feedback_card(pre, tile):
    text = (":material/rate_review: **How's Venato treating you?**" if tile else
            ":material/rate_review: **How's Venato treating you?** Tell us what's annoying or missing. "
            "It opens a short form in your browser.")
    row = _card_row(text, tile)
    row.link_button("Send feedback", feedback.feedback_url(), icon=":material/open_in_new:",
                    key=f"{pre}needs_fb_yes", on_click=feedback.card_done)
    row.button("Not now", key=f"{pre}needs_fb_no", type="tertiary", on_click=feedback.card_done,
               help="Hide this for good. Send feedback stays in Settings → About.")


def _needs_goals(rows, ctx):
    from venato.ui import goals
    st.html(goals.goal_bar_css())
    for p, state, what in rows:            # each goal: its pill and what it needs, then its bar
        g = p["goal"]
        head = st.container(horizontal=True, vertical_alignment="center", gap="small")      # no float: it overlapped the bar
        pill = NEEDS_PLAN if state == "needs_plan" else f":{PILL[state]}-badge[{ICONS[state]} {pace.STATES[state]}]"
        head.markdown(f"{pill} **{md(g['title'])}**", width="stretch")
        if what:
            head.markdown(md(what), width="content")
        line = " · ".join(x for x in (f"{goals.amount(g)} {store.goal_title_due(g['due'], ctx.today)}",
                                      goals.pace_detail(p)) if x)
        st.html(goals.goal_bar(g, ctx.today, line))
    if any(p.get("week") and p["week"]["short"] >= pace.TOLERANCE and not p["week"]["over"] for p, _, _ in rows):
        if st.button("Plan my goals", icon=":material/auto_awesome_motion:", key="home_plan_goals", width="stretch",
                     help="Fill what each goal is short into free time this week, top goal first. You'll see it first."):
            from venato.ui import timetable_tools
            timetable_tools.open_plan_goals(ctx.today)


def offers(ctx=None):
    """Cards for goals that can't be finished with the time (or days) left: lower the target, move the deadline or take hours."""
    ctx = ctx or _ctx()
    if _confirm_box():
        return
    gone = pace.dismissed_offers()
    for g in pace.goals_active(ctx.today):
        if g["id"] in gone:
            continue
        n = pace.negotiation(g, ctx)
        if not n:
            continue
        with st.container(border=True, key=f"offer_card_{g['id']}"):
            p = n["pace"]
            kit.subhead(f"{g['title']} can't be finished in time", icon=":material/error:")
            st.caption(f"{md(pace.amount(g, p['remaining']))} to go, about "
                       f"{md(pace.amount(g, n['reachable'] - p['value']))} within reach.")
            for o in n["offers"]:
                st.button(o["text"], key=f"offer_{o['kind']}_{g['id']}", on_click=_offer, args=(g["id"], o["kind"]),
                          width="stretch")
            st.button("Not now", key=f"offer_no_{g['id']}", type="tertiary", on_click=pace.dismiss_offer,
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
