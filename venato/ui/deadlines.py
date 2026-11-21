"""
Deadlines: things due on a date, with a countdown.

Home lists the next few (overdue ones in red). The Goals page has the full list:
add, tick off, edit, delete, and "Plan": an hours goal in the deadline's module, finishing by a day you
pick (by default the day before it's due). A plan's goal then gets pace, carry-over and suggested sittings
like any other; the row says how it's going ("6 / 15 h · on track"). Ticking the deadline done closes the
plan, and deleting the deadline deletes it.
"""

from datetime import timedelta

import streamlit as st

from venato import regional
from venato import store
from venato import undo
from venato.ui.goal_time import md
from venato.ui import glance, kit

HOME_LIMIT = 5


def _go_to_goals():
    st.session_state["page"] = "Goals"


def open_module(mid):
    """Go to a module's page (the Modules page, showing that module)."""
    st.session_state["gr_module"] = mid
    st.session_state["page"] = "Modules"


def _modules_on():
    from venato import blocks
    return blocks.is_on("grades")


def lazy_ctx():
    """A pace.Ctx made the first time it's asked for (it reads the timetable), then reused by every row."""
    box = []

    def get():
        if not box:
            from venato import pace
            box.append(pace.Ctx())
        return box[0]
    return get


def plan_line(d, ctx_for):
    """"6 / 15 h · on track" for a deadline with a plan, else "". ctx_for() gives the page's pace.Ctx."""
    goal = store.deadline_goal(d["id"])
    if not goal:
        return ""
    from venato import pace
    p = pace.goal_pace(goal, ctx_for())
    return f"{pace.fmt(goal['value'])} / {pace.fmt(goal['target'])} h · {pace.STATES[p['state']].lower()}"


def _tone(d, today):
    """"over" once it's past its due time (or day), "soon" within 2 days."""
    days = (store._as_date(d["due"]) - today).days
    return "over" if store.deadline_overdue(d) else "soon" if days <= 2 else ""


def _when(d, today):
    """Its countdown, with its due time when it has one ("Today, 17:00", "Overdue since 17:00")."""
    return store.countdown(d["due"], today, d.get("due_time"), store.local_now())


def _pill_tone(d, today):
    """Home's countdown pill: red overdue or due today, amber within 3 days, grey later."""
    days = (store._as_date(d["due"]) - today).days
    return "red" if days <= 0 or store.deadline_overdue(d) else "amber" if days <= 3 else "grey"


def render_home():
    """Home's Deadlines widget: what's due, soonest first, each with its countdown in a coloured pill."""
    today = store.local_today()
    rows = store.deadlines()
    head = st.container(horizontal=True, vertical_alignment="center")
    kit.subhead("Deadlines", head, width="stretch")
    head.button("See all", key="home_deadlines_all", type="tertiary", on_click=_go_to_goals)
    if not rows:
        st.caption("Nothing due. Add deadlines on the Goals page.")
        return
    st.html("""<style>
      .st-key-dl_home [data-testid="stButton"] button { width: 100%; justify-content: flex-start; min-height: 0;
        padding: 2px 0; font-size: 0.88rem; }
      .st-key-dl_home p { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    </style>""")
    with st.container(key="dl_home", gap="xxsmall"):
        for d in rows[:HOME_LIMIT]:
            label = f"{md(d['title'])}  " + glance.pill(_when(d, today), _pill_tone(d, today))
            if d["module_id"] and _modules_on():
                st.button(label, key=f"dl_home_{d['id']}", type="tertiary", on_click=open_module, args=(d["module_id"],),
                          help="Open its module")
            else:
                st.markdown(label)
        if len(rows) > HOME_LIMIT:
            st.caption(f"and {len(rows) - HOME_LIMIT} more")


@st.dialog("Edit deadline")
def _edit_dialog(did):
    d = store.get_deadline(did)
    if not d:
        st.caption("That deadline is gone.")
        return
    with st.form(f"dl_edit_{did}", border=False):
        title = st.text_input("What's due", d["title"])
        due = st.date_input("Due", store._as_date(d["due"]), format=regional.input_format())
        from venato.blocks import grades as gr
        mods = gr.modules()
        ids = [None] + [m["id"] for m in mods]
        names = {m["id"]: m["name"] for m in mods}
        module = st.selectbox("Module", ids, index=ids.index(d["module_id"]) if d["module_id"] in ids else 0,
                              format_func=lambda i: names.get(i, "None")) if mods else d["module_id"]
        notes = st.text_area("Notes", d["notes"] or "", height=80)
        if st.form_submit_button("Save", type="primary"):
            if not title.strip():
                st.error("Say what's due.")
            else:
                store.update_deadline(did, title=title, due=due, notes=notes, module_id=module)
                st.rerun()
    st.divider()
    if st.button("Delete this deadline", icon=":material/delete:", key=f"dl_del_{did}"):
        undo.checkpoint(f"Deleted the deadline '{d['title']}'")
        store.delete_deadline(did)
        st.rerun()


def _toggle(did, key):
    store.set_deadline_done(did, st.session_state[key])


@st.dialog("Plan this deadline")
def _plan_dialog(did):
    """Total hours or hours a week, the category the hours count in (a module's, or any, for someone with no
    modules) and a finish-by day."""
    from venato.blocks import grades as gr
    d = store.get_deadline(did)
    if not d or d["done"]:
        st.caption("That deadline is gone or done.")
        return
    mods = gr.modules()
    cats = store.load_categories().to_dict("records")
    today, due = store.local_today(), store._as_date(d["due"])
    module = gr.get_module(d["module_id"]) if d["module_id"] else None
    if module and not module["category_id"]:
        st.info(f"{module['name']} has no category yet, and a plan needs one to count its hours.",
                icon=":material/category:")
        if st.button("Create its category", icon=":material/add:", key=f"plan_cat_{did}", type="primary"):
            gr.create_category(module["id"])
            st.rerun()
        return
    if not cats:
        from venato.ui import timetable_tools
        timetable_tools.no_categories(f"plan_nocat_{did}", "A plan counts its hours in a timetable category. "
                                      "Add one first.")
        return
    st.markdown(f"**{md(d['title'])}** · due {regional.day_month(due)}")
    ids = [c["id"] for c in cats]
    goal = store.deadline_goal(did)
    start = goal["category_id"] if goal and goal.get("category_id") else module["category_id"] if module else None
    cid = st.selectbox("Counts in", ids, index=ids.index(start) if start in ids else 0,
                       format_func=lambda i: next(c["name"] for c in cats if c["id"] == i), key=f"plan_cat_pick_{did}",
                       help="The hours count in this category. A module's category also holds its lectures.")
    mid = next((m["id"] for m in mods if m["category_id"] == cid), None)       # a module's own category links it
    how = st.radio("Hours", ["In total", "A week"], horizontal=True, key=f"plan_how_{did}",
                   index=0, help="A week: the hours for each week from today to the finish-by day.")
    hours = st.number_input("Hours" if how == "In total" else "Hours a week", 0.5, 500.0,
                            float(goal["target"]) if goal and how == "In total" else 6.0 if how == "In total" else 3.0,
                            0.5, key=f"plan_hours_{did}_{how}")
    default = (store._as_date(goal["due"]) if goal else max(today, due - timedelta(days=1)))
    finish = st.date_input("Finish by", min(max(default, today), due), min_value=today, max_value=due,
                           format=regional.input_format(), key=f"plan_by_{did}",
                           help="By default the day before it's due.")
    row = st.container(horizontal=True)
    if row.button("Save plan" if goal else "Plan", type="primary", key=f"plan_go_{did}"):
        try:
            if mid and d["module_id"] != mid:
                store.update_deadline(did, module_id=mid)
            store.plan_deadline(did, cid, total=hours if how == "In total" else None,
                                per_week=hours if how == "A week" else None, finish_by=finish)
        except ValueError as e:
            st.error(str(e))
        else:
            st.rerun()
    if goal and row.button("Remove plan", key=f"plan_rm_{did}"):
        undo.checkpoint(f"Removed the plan for '{d['title']}'")
        store.delete_goal(goal["id"])
        st.rerun()


def row(d, today, ctx_for=None):
    """One deadline: tick, title (with its module and plan line), when, edit, and Plan."""
    ctx_for = ctx_for or lazy_ctx()
    tick, title, when, edit, plan = st.columns([0.5, 5, 2, 0.6, 1.4], vertical_alignment="center")
    key = f"dl_done_{d['id']}"
    tick.checkbox("Done", value=d["done"], key=key, label_visibility="collapsed",
                  on_change=_toggle, args=(d["id"], key))
    tone = {"over": ":red", "soon": ":orange"}.get(_tone(d, today), "")
    with title:
        st.markdown(f"~~{md(d['title'])}~~" if d["done"] else f"**{md(d['title'])}**"
                    + (f"  \n:gray[{md(d['notes'])}]" if d["notes"] else ""))
        module = None
        if d["module_id"]:
            from venato.blocks import grades as gr
            module = gr.get_module(d["module_id"])
        line = "" if d["done"] else plan_line(d, ctx_for)
        if module and _modules_on():
            st.button(module["name"] + (f" · {line}" if line else ""), key=f"dl_mod_{d['id']}", type="tertiary",
                      icon=":material/school:", on_click=open_module, args=(module["id"],), help="Open its module")
        elif line:
            st.caption(line)
    due = store._as_date(d["due"])
    text = regional.day_month(due) + ("" if d["done"] else f" · {_when(d, today)}")
    when.markdown(f"{tone}[{text}]" if tone and not d["done"] else text)
    if edit.button("", icon=":material/edit:", key=f"dl_edit_btn_{d['id']}", help="Edit or delete"):
        _edit_dialog(d["id"])
    if not d["done"] and due >= today and plan.button(
            "Plan", icon=":material/event_available:", key=f"dl_plan_{d['id']}",
            help="Plan hours for it: they count in its module and get suggested sittings"):
        _plan_dialog(d["id"])


def render_section():
    today = store.local_today()
    with st.container(border=True):
        rows = store.deadlines(include_done=True)
        open_ = [d for d in rows if not d["done"]]
        st.subheader(f"Deadlines :gray[{len(open_)}]", anchor=False)
        ctx_for = lazy_ctx()
        for d in open_:
            row(d, today, ctx_for)
        if not open_:
            st.caption("Nothing due.")
        with st.form("dl_new", clear_on_submit=True, border=False):
            a, b, c = st.columns([5, 2, 1], vertical_alignment="bottom")
            title = a.text_input("New deadline", placeholder="e.g. Essay, Internship application")
            due = b.date_input("Due", today + timedelta(days=7), format=regional.input_format())
            if c.form_submit_button("Add", icon=":material/add:") and title.strip():
                store.add_deadline(title, due)
                st.rerun()
        done = [d for d in rows if d["done"]]
        if done:
            with st.expander(f"Done ({len(done)})"):
                for d in reversed(done[-20:]):
                    row(d, today, ctx_for)
