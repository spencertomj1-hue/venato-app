"""One module's page (Modules, after clicking a module): this week's lectures, its deadlines (with Plan),
its assessments and what it needs on the rest, its hours this week and since you added it, its timetable
blocks, Fit time, and Links (its code, title words, Canvas course and lecture series). The numbers come from venato/blocks/grades.py."""

from html import escape

import streamlit as st

from venato import pace
from venato import regional
from venato import store
from venato.blocks import grades as gr
from venato.ui import deadlines, kit
from venato.ui import grades as page
from venato.ui.goal_time import md

OPEN = "gr_module"


def back():
    st.session_state.pop(OPEN, None)


def _slot(item):
    """"Mon 3 Nov, 10:00-11:00" for a lecture or block."""
    day = store.fmt_day(store._as_date(item["date"]), "%a %-d %b")
    return f"{day}, {regional.time(item['start'])}-{regional.time(item['end'])}" if item.get("start") else day


def _needs_line(m, n):
    """What the module needs on the rest: "You need 68% on the remaining 50% for 70%"."""
    if m["final"] is not None:
        return f"Final mark {m['final']:g}%."
    if m["target"] is None:
        return "Set a target to see what you need on the rest."
    if n["needed"] is None:
        return "Everything is marked."
    if n["status"] == "reached":
        return f"Target {m['target']:g}% already reached."
    if n["status"] == "impossible":
        return f"Target {m['target']:g}% is out of reach."
    return f"You need **{n['needed']:.0f}%** on the remaining {n['left']:g}% for {m['target']:g}%."


def _lectures(m, week):
    kit.section("This week's lectures")
    rows = [e for e in gr.week_events(m["id"], week[0], week[-1]) if not e["all_day"]]
    if not rows:
        kit.empty("No lectures this week. Import your uni timetable in Settings to see them here.",
                  ":material/event_busy:")
    for e in rows:
        st.markdown(f":material/school: **{md(e['title'])}**  \n:gray[{md(_slot(e))}"
                    + (f" · {md(e['location'])}" if e.get("location") else "") + "]")


def _deadlines(m, today, ctx_for):
    kit.section("Upcoming deadlines")
    rows = gr.open_deadlines(m["id"])
    if not rows:
        kit.empty("Nothing due for this module.", ":material/event_available:")
    for d in rows:
        deadlines.row(d, today, ctx_for)


def _assessments(m, n):
    kit.section("Assessments")
    st.markdown(_needs_line(m, n))
    page.assessment_editor(m)


def _hours(m, ctx):
    kit.section("Hours")
    if not m["category_id"]:
        _no_category(m, "Its hours count in its category.")
        return
    h = gr.module_hours(m, ctx)
    f = pace.fmt
    kit.bars([{"label": "This week", "frac": min(1.0, h["done"] / h["goal"]) if h["goal"] else 0,
               "colour": gr.category_colour(m) or "#4E79A7",
               "value": f"{f(h['done'])} done · {f(h['planned'])} planned · {f(h['goal'])} h goal"}])
    st.caption(f"{f(h['term'])} h since you added it.")
    mine = (store.load_settings().get("module_hours") or {}).get(m["id"])
    new = st.number_input("Hours a week for this module", 0.0, 80.0, h["goal"], 0.5, key=f"gr_wh_{m['id']}",
                          help=f"Your goal for it each week. Left alone it's {gr.DEFAULT_WEEK_HOURS} h like every module.")
    if new != h["goal"] and new != mine:
        gr.set_week_hours_goal(m["id"], new)
        st.rerun()


def _no_category(m, why):
    st.caption(f"{m['name']} has no category yet. {why}")
    if st.button("Create its category", key=f"gr_cat_{m['id']}", icon=":material/add:"):
        gr.create_category(m["id"])
        st.rerun()


def _blocks(m, week):
    kit.section("Its timetable blocks")
    rows = gr.week_blocks(m, week[0], week[-1]) if m["category_id"] else []
    if not rows:
        kit.empty("Nothing planned for it this week.", ":material/event_busy:")
    for b in rows:
        st.markdown(f":material/schedule: {md(b['label'] or m['name'])} · :gray[{md(_slot(b))}]")


def _fit(m, ctx, week):
    if not m["category_id"]:
        return
    h = gr.module_hours(m, ctx)
    short = max(0.5, pace.half_up(h["goal"] - h["planned"]))
    if st.button(f"Fit time ({pace.fmt(short)} h)", icon=":material/event_available:", key=f"gr_fit_{m['id']}",
                 help="Fit the hours it's short this week into your free time"):
        from venato.ui import timetable_tools
        timetable_tools.open_fit(m["name"], week[-1], category=m["name"], hours=short, first=max(week[0], ctx.today))


def _set(mid, field, key):
    try:
        gr.update_module(mid, **{field: st.session_state.get(key)})
    except gr.GradeError as e:
        st.session_state["gr_links_error"] = str(e)


def _link_course(mid, old, key):
    new = st.session_state.get(key)
    if old and old != new:
        gr.link_canvas_course(old, None)
    if new:
        gr.link_canvas_course(new, mid)


def _links(m):
    """What's linked to the module and how: its code, a title rule, its Canvas course, and its lecture series
    (each can be taken off it)."""
    if err := st.session_state.pop("gr_links_error", None):
        st.error(err)
    st.caption("Lectures join a module by its code, else by words in their titles (its name when it has no code).")
    a, b, c = st.columns(3)
    a.text_input("Code", m["code"] or "", key=f"gr_code_{m['id']}", placeholder="e.g. CHEM50001",
                 on_change=_set, args=(m["id"], "code", f"gr_code_{m['id']}"))
    b.text_input("Lecture titles contain", m["match"] or "", key=f"gr_match_{m['id']}",
                 placeholder=m["name"] if not m["code"] else "e.g. Organic",
                 help="Words a lecture's title must have to count for this module",
                 on_change=_set, args=(m["id"], "match", f"gr_match_{m['id']}"))
    known = {x["course_id"]: x for x in gr.canvas_courses()}
    for x in gr.detected_courses():
        known.setdefault(x["course_id"], x)
    mine = next((cid for cid, x in known.items() if x["module_id"] == m["id"]), None)
    options = [None, *known]
    c.selectbox("Canvas course", options, index=options.index(mine), key=f"gr_canvas_{m['id']}",
                format_func=lambda cid: "None" if cid is None else (known[cid]["label"] or cid),
                on_change=_link_course, args=(m["id"], mine, f"gr_canvas_{m['id']}"))
    series = gr.series_of(m["id"], store.local_today())
    if not series:
        st.caption("No lectures linked in the next 8 weeks.")
    for i, x in enumerate(series):
        text, btn = st.columns([4, 1], vertical_alignment="center")
        text.markdown(f":material/school: **{md(x['title'])}** · {x['count']} sessions")
        btn.button("Not this module", key=f"gr_notthis_{m['id']}_{i}", on_click=gr.file_series, args=(x["title"], None))


def render(m):
    ctx = pace.Ctx()
    week = pace.week_days(ctx.today)
    n = gr.module_numbers(m)
    colour = gr.category_colour(m)
    st.button("All modules", icon=":material/arrow_back:", key="gr_back", type="tertiary", on_click=back)
    dot = (f'<span style="display:inline-block;width:.8em;height:.8em;border-radius:50%;background:{colour};'
           f'margin-right:.4em"></span>') if colour else ""
    st.html(f'<h2 style="margin:0">{dot}{escape(m["name"])}</h2>')
    st.caption(" · ".join(b for b in (m["code"], f"{m['credits']:g} credits", m["year"]) if b))
    label, tone = page.band(n["projected"])
    st.markdown(f"Mark **{'–' if n['projected'] is None else f'{n['projected']:.0f}%'}**"
                + (f" ({label})" if n["projected"] is not None else "")
                + (f" · target {m['target']:g}%" if m["target"] is not None else ""))
    _fit(m, ctx, week)
    ctx_for = lambda: ctx
    a, b = st.columns(2, gap="medium")
    with a, kit.card(stretch=False):
        _lectures(m, week)
    with b, kit.card(stretch=False):
        _deadlines(m, ctx.today, ctx_for)
    with st.container(border=True):
        _assessments(m, n)
    c, d = st.columns(2, gap="medium")
    with c, kit.card(stretch=False):
        _hours(m, ctx)
    with d, kit.card(stretch=False):
        _blocks(m, week)
    with st.expander("Links", icon=":material/link:"):
        _links(m)
    with st.expander("Module settings", icon=":material/tune:"):
        page.module_settings(m)
