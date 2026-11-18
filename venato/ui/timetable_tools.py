"""
Buttons above the timetable, so everything works without the Claude assistant:

  Fit time     smart scheduling: fit N hours of something into the Plan's free gaps
  Categories   add / rename / recolour categories, activity defaults, Outlook's colour

They call the same functions as Claude's tools (tools.add_block, plan_time,
edit_category, ...), so the rules and the Confirm previews are identical.
"""

from datetime import timedelta

import re

import streamlit as st

from venato import regional
from venato import store
from venato import undo
from venato import tools

AUTO = "Automatic (from the activity)"
PENDING = "tt_tool_pending"          # a tools.Pending preview waiting for Confirm


def _times(first, last):
    return [store.slot_time(i) for i in range(first, last + 1)]


def _at(options, wanted, fallback=0):
    """Index of a default time in a list of times (or the fallback if the day doesn't include it)."""
    return options.index(wanted) if wanted in options else min(fallback, len(options) - 1)


def _category_names():
    return list(store.load_categories()["name"])


def _for_people(message):
    """Tool errors are worded for Claude ("Ask the user ..."); drop those bits for a person."""
    message = re.sub(r"\s*(Ask the user|Use list_\w+|Set create=true)[^.]*(: [^.]*)?\.", "", message)
    return message.replace("There's no default category for", "Pick a category: there's no default for")


def _category_choice(label, category):
    """None for Automatic, else the picked name; shows an error (and returns False) if Automatic can't work."""
    if category != AUTO:
        return category
    if label.strip() and store.resolve_category(label=label.strip()) is None:
        st.error(f"Pick a category for “{label.strip()}” (it has no default yet; you can set one in Categories).",
                 icon=":material/error:")
        return False
    return None


def _call(fn, *args, apply_now=False, **kwargs):
    """Run a tool and refresh the page. A preview waits for Confirm, or with apply_now
    (overwriting by hand) goes straight ahead with an Undo instead."""
    try:
        r = fn(*args, **kwargs)
    except tools.ToolError as e:
        st.error(_for_people(str(e)), icon=":material/error:")
        return
    if r.pending and apply_now:
        undo.checkpoint(r.pending.summary)
        r = r.pending.run()
    if r.pending:
        st.session_state[PENDING] = r.pending
        st.rerun(scope="fragment")
    st.session_state.pop(PENDING, None)
    st.toast(r.text, icon=":material/check_circle:")
    st.rerun()


def _confirm_box(yes="Confirm"):
    """Show a waiting preview with Confirm / Cancel; True while one is waiting."""
    pending = st.session_state.get(PENDING)
    if not pending:
        return False
    st.warning(pending.summary, icon=":material/preview:")
    a, b, _ = st.columns([1, 1, 3])
    if a.button(yes, type="primary", key="tt_tool_yes"):
        undo.checkpoint(pending.summary)
        r = pending.run()
        st.session_state.pop(PENDING, None)
        st.toast(r.text, icon=":material/check_circle:")
        st.rerun()
    if b.button("Cancel", key="tt_tool_no"):
        st.session_state.pop(PENDING, None)
        st.rerun(scope="fragment")
    return True


# ---------------------------------------------------------------------------
# Fit time (smart scheduling)
# ---------------------------------------------------------------------------

@st.dialog("Fit time into your Plan", width="large")
def _fit_dialog(day, label="", last=None, category=None, hours=6.0):
    st.caption("Finds free gaps in your Plan (around your blocks and Outlook events) and spreads the "
               "hours over the days, with a break between sittings. You'll see the times before anything is added.")
    if _confirm_box("Add to Plan"):
        return
    today = store.local_today()
    first = max(day, today)
    last = max(first, last) if last else first + timedelta(days=6)
    with st.form("tt_fit_form", border=False):
        a, b = st.columns([2, 1])
        label = a.text_input("What", value=label, placeholder="e.g. Revision")
        hours = b.number_input("Hours in total", 0.5, 60.0, float(min(60.0, max(0.5, hours))), step=0.5)
        options = [AUTO] + _category_names()
        category = st.selectbox("Category", options, key="tt_fit_cat",
                                index=options.index(category) if category in options else 0)
        a, b = st.columns(2)
        span = a.date_input("Between", value=(first, last), format=regional.input_format(),
                            help="Pick the first and last day.")
        longest = b.number_input("Longest sitting (hours)", 0.5, 8.0, 2.0, step=0.5)
        a, b, c = st.columns([1, 1, 1], vertical_alignment="bottom")
        starts, ends = _times(0, store.SLOTS - 1), _times(1, store.SLOTS)
        earliest = a.selectbox("Not before", starts, index=_at(starts, "09:00"), format_func=regional.time)
        latest = b.selectbox("Not after", ends, index=_at(ends, "21:00", len(ends) - 1), format_func=regional.time)
        weekdays = c.checkbox("Weekdays only")
        if st.form_submit_button("Find times", type="primary", icon=":material/event_available:"):
            if not label.strip():
                st.error("Say what it's for, e.g. Revision.")
            elif len(span) != 2:
                st.error("Pick both the first and the last day.")
            elif (cat := _category_choice(label, category)) is not False:
                _call(tools.plan_time, label, hours, span[0].isoformat(), span[1].isoformat(),
                      category=cat, earliest=earliest, latest=latest,
                      max_block_hours=longest, weekdays_only=weekdays)


# ---------------------------------------------------------------------------
# Categories, activity defaults and Outlook's colour
# ---------------------------------------------------------------------------

@st.dialog("Adjust categories", width="large")
def _categories_dialog():
    cats = store.load_categories().to_dict("records")
    groups = store.groups()

    st.markdown("**Your categories**")
    with st.form("tt_cats_form", border=False):
        edits = []
        for c in cats:
            a, b, g = st.columns([4, 1, 2], vertical_alignment="bottom")
            name = a.text_input("Name", c["name"], key=f"tt_cat_name_{c['id']}", label_visibility="collapsed")
            colour = b.color_picker("Colour", c["colour"], key=f"tt_cat_col_{c['id']}", label_visibility="collapsed")
            grp = g.selectbox("Group", groups, index=groups.index(c["grp"]), key=f"tt_cat_grp_{c['id']}",
                              label_visibility="collapsed")
            edits.append((c, name.strip(), colour, grp))
        if st.form_submit_button("Save changes", type="primary", icon=":material/save:"):
            names = [n.lower() for _, n, _, _ in edits]
            if any(not n for n in names):
                st.error("Every category needs a name.")
            elif len(set(names)) < len(names):
                st.error("Two categories can't have the same name.")
            else:
                for c, name, colour, grp in edits:
                    if (name, colour.upper(), grp) != (c["name"], c["colour"].upper(), c["grp"]):
                        store.save_category(c["id"], name, colour, grp, c["text_colour"])
                st.toast("Categories saved", icon=":material/check_circle:")
                st.rerun()

    st.markdown("**New category**")
    with st.form("tt_cat_new", clear_on_submit=True, border=False):
        a, b, g, s = st.columns([4, 1, 2, 2], vertical_alignment="bottom")
        name = a.text_input("Name", placeholder="e.g. Music")
        colour = b.color_picker("Colour", "#3E8EF7")
        grp = g.selectbox("Group", groups)
        if s.form_submit_button("Add", icon=":material/add:"):
            if not name.strip():
                st.error("Give it a name.")
            else:
                _call(tools.edit_category, name, colour=colour, group=grp, create=True)

    st.divider()
    st.markdown("**Activity defaults**")
    st.caption("Typing one of these in the timetable picks its category automatically.")
    names = dict(zip(store.load_categories()["id"], store.load_categories()["name"]))
    for row in store.load_label_map().to_dict("records"):
        a, b, c = st.columns([3, 3, 1], vertical_alignment="center")
        a.write(row["label"])
        b.write(names.get(row["category_id"], "—"))
        if c.button("", icon=":material/delete:", key=f"tt_lab_del_{row['label']}", help="Remove"):
            store.remove_label_default(row["label"])
            st.rerun(scope="fragment")
    with st.form("tt_lab_new", clear_on_submit=True, border=False):
        a, b, c = st.columns([3, 3, 1], vertical_alignment="bottom")
        label = a.text_input("Activity", placeholder="e.g. Piano")
        cat = b.selectbox("Category", list(names.values()))
        if c.form_submit_button("Add", icon=":material/add:"):
            _call(tools.set_activity_default, label, cat)

    st.divider()
    st.markdown("**Outlook events**")
    current = store.outlook_category("")
    ids = list(names)
    pick = st.selectbox("Colour Outlook events as", ids, index=ids.index(current) if current in ids else 0,
                        format_func=names.get, key="tt_outlook_cat")
    if pick != current:
        store.save_settings(outlook_category=pick)
        st.toast(f"Outlook events now use {names[pick]}", icon=":material/check_circle:")


# ---------------------------------------------------------------------------
# The toolbar
# ---------------------------------------------------------------------------

def open_fit(label, last, category=None, hours=6.0, first=None):
    """Fit time for something specific (a deadline, a goal that's short), finishing by `last`."""
    st.session_state.pop(PENDING, None)
    names = _category_names()
    if category not in names:
        category = "Study" if "Study" in names else None
    _fit_dialog(first or store.local_today(), label, last, category, hours)


@st.dialog("Plan time for your goals", width="large")
def _plan_goals_dialog(week):
    st.caption("Fills what each goal that counts timetable hours is short this week into free time in your "
               "Plan, top goal first. Nothing already there is moved or overwritten.")
    if _confirm_box("Add to Plan"):
        return
    try:
        r = tools.plan_goals(week.isoformat())
    except tools.ToolError as e:
        st.error(_for_people(str(e)), icon=":material/error:")
        return
    if r.pending:
        st.session_state[PENDING] = r.pending
        _confirm_box("Add to Plan")
    else:
        st.info(r.text, icon=":material/info:")


def open_plan_goals(week):
    """Plan my goals: tools.plan_goals for the week containing `week`, previewed with Confirm / Cancel."""
    st.session_state.pop(PENDING, None)
    _plan_goals_dialog(week)


@st.dialog("Confirm the week")
def _confirm_week_dialog(first, last):
    st.caption("Each day of this week that has passed and isn't confirmed yet: its Actual, as it is on the timetable "
               "now, is what you did. Stats and goals then count those days.")
    if _confirm_box("Confirm"):
        return
    try:
        r = tools.confirm_day(first.isoformat(), last.isoformat(), preview=True)
    except tools.ToolError as e:
        st.error(_for_people(str(e)), icon=":material/error:")
        return
    if r.pending:
        st.session_state[PENDING] = r.pending
        _confirm_box("Confirm")
    else:
        st.info(r.text, icon=":material/info:")


@st.dialog("Confirm all")
def _confirm_all_dialog():
    st.caption("Every day that has passed and isn't confirmed yet, in every week: its Actual, as it is on the "
               "timetable now, is what you did. Stats and goals then count those days.")
    if _confirm_box("Confirm"):
        return
    r = tools.confirm_all()
    if r.pending:
        st.session_state[PENDING] = r.pending
        _confirm_box("Confirm")
    else:
        st.info(r.text, icon=":material/info:")


# Fit time / Adjust categories: soft tinted pills with a coloured icon (blue: fills the Plan; orange: the
# palette), not plain white buttons. !important and .stApp: Paper's button style (paper.py) is !important too.
_TOOL_CSS = """<style>
.stApp .st-key-tt_btn_fit [data-testid^="stBaseButton"] { --c: #2f7de1; }
.stApp .st-key-tt_btn_cats [data-testid^="stBaseButton"] { --c: #e0782f; }
.stApp .st-key-tt_btn_fit [data-testid^="stBaseButton"], .stApp .st-key-tt_btn_cats [data-testid^="stBaseButton"] {
  min-height: 2rem !important; padding: 0.2rem 0.95rem !important; border-radius: 999px !important;
  border: 1px solid color-mix(in srgb, var(--c) 35%, transparent) !important;
  background: color-mix(in srgb, var(--c) 10%, transparent) !important;
  font-weight: 600 !important; transition: background 0.15s, border-color 0.15s, transform 0.15s, box-shadow 0.15s;
}
.stApp .st-key-tt_btn_fit [data-testid^="stBaseButton"]:hover, .stApp .st-key-tt_btn_cats [data-testid^="stBaseButton"]:hover {
  background: color-mix(in srgb, var(--c) 18%, transparent) !important; border-color: var(--c) !important;
  transform: translateY(-1px); box-shadow: 0 3px 10px color-mix(in srgb, var(--c) 25%, transparent);
}
.stApp .st-key-tt_btn_fit [data-testid^="stBaseButton"]:active, .stApp .st-key-tt_btn_cats [data-testid^="stBaseButton"]:active {
  transform: none; box-shadow: none;
}
.st-key-tt_btn_fit [data-testid="stIconMaterial"], .st-key-tt_btn_cats [data-testid="stIconMaterial"] { color: var(--c); }
</style>"""


def toolbar(day, row=None):
    """Confirm week / Fit time / Adjust categories, into `row` if given (the Timetable's one toolbar line)."""
    row = row or st.container(horizontal=True, gap="small")     # sized to the text, so bigger text never truncates
    st.html(_TOOL_CSS)
    b = c = row
    first = store.week_start_of(day)
    waiting = store.unconfirmed_days(first, min(first + timedelta(days=6), store.local_today()))
    everything = store.unconfirmed_days_with_blocks()
    if everything and row.button(f"Confirm all ({len(everything)} day{'s' if len(everything) > 1 else ''})",
                                 icon=":material/done_all:", key="tt_btn_confirm_all",
                                 help="Confirm every past day that isn't confirmed yet, in every week"):
        st.session_state.pop(PENDING, None)
        _confirm_all_dialog()
    if waiting and set(waiting) != set(everything) and row.button(f"Confirm week ({len(waiting)} day{'s' if len(waiting) > 1 else ''})",
                              icon=":material/task_alt:", key="tt_btn_confirm_week",
                              help="Only confirmed days count in stats and goals: confirm that each day's Actual is what you did"):
        st.session_state.pop(PENDING, None)
        _confirm_week_dialog(first, first + timedelta(days=6))
    if b.button("Fit time", icon=":material/event_available:", key="tt_btn_fit",
                help="Fit hours of something (e.g. 6 h of revision) into your free time"):
        st.session_state.pop(PENDING, None)
        _fit_dialog(day)
    if c.button("Adjust categories", icon=":material/palette:", key="tt_btn_cats"):
        _categories_dialog()
