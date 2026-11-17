"""
Timetable page: a week at a time in 30-minute slots, coloured by category. One column a day,
showing either the Plan or the Actual (a Plan / Actual switch on the grid). A day's Plan is locked
when the day starts (store.lock_day); after that every change is to its Actual, which the user
confirms at the end of the day.

The week grid is a small custom Streamlit component (timetable_component.js/.css).
It paints locally for instant feedback and sends edit operations back here.
What gets saved is computed by store.plan_paint, the same rules the Claude
assistant's add_block tool uses.
"""

from datetime import date, datetime, timedelta
from pathlib import Path

import streamlit as st

from venato import outlook
from venato import regional
from venato import store

HERE = Path(__file__).parent
SYNC_EVERY = timedelta(minutes=15)

# The grid component, built once from the JS/CSS files next to this module.
_timetable_component = st.components.v2.component(
    "daily_timetable",
    html='<div class="tt-root"></div>',
    css=(HERE / "components" / "timetable_component.css").read_text(encoding="utf-8"),
    js=(HERE / "components" / "timetable_component.js").read_text(encoding="utf-8"),
)


# ---------------------------------------------------------------------------
# Grid callbacks
# ---------------------------------------------------------------------------

def _overlapping(date, track, s, e):
    """Labels of the blocks (and, in the Plan, Outlook events) a paint would cover."""
    labels = [b["label"] for b in store.blocks_between(date, date, track)
              if store.slot_of(b["start"]) < e and store.slot_of(b["end"]) > s]
    if track == "plan":
        labels += [ev["title"] for ev in store.outlook_between(date, date)
                   if not ev["all_day"] and ev["start"] and store.slot_of(ev["start"]) < e and store.slot_of(ev["end"]) > s]
    return labels


def _checkpoint(op):
    """Before a grid change that deletes or overwrites something, save an Undo point for it. Quiet:
    no Undo bar pops up on the timetable, but Cmd/Ctrl+Z still brings it back."""
    from venato import undo     # (confirming a day never overwrites anything: no Undo point needed)
    kind = op["kind"]
    if kind == "paint":
        s, e = store.slot_of(op["start"]), store.slot_of(op["end"])
        covered = _overlapping(op["date"], op["track"], s, e)
        if covered:
            what = ", ".join(dict.fromkeys(covered))
            undo.checkpoint(f"Erased {what}" if not op.get("block") else f"Painted over {what}", quiet=True)
    elif kind == "delete":
        b = store.get_block(op["id"])
        undo.checkpoint(f"Deleted {b['label']}" if b else "Deleted a block", quiet=True)
    elif kind == "upsert":
        undo.checkpoint(f"Edited {op['entry'].get('label') or 'a block'}", quiet=True)
    elif kind == "hide_outlook":
        undo.checkpoint("Removed an Outlook event from the timetable", quiet=True)
    elif kind == "add_suggestion":                       # nothing is overwritten, but Cmd/Ctrl+Z takes it back
        undo.checkpoint(f"Added a suggested sitting of {op['block']['label']}", quiet=True)
    elif kind in ("skip", "replace", "retime"):          # corrections on the one timeline
        what = {"skip": "Marked as not done", "replace": "Changed what happened", "retime": "Changed the times"}[kind]
        undo.checkpoint(f"{what} on {op['date']}", quiet=True)
    elif kind == "move":
        b = store.get_block(op["id"])
        what = b["label"] if b else "the block"
        length = lambda start, end: store.slot_of(end) - store.slot_of(start)
        resized = b and length(b["start"], b["end"]) != length(op["start"], op["end"])
        undo.checkpoint(f"Changed {what}'s times" if resized else f"Moved {what}", quiet=True)      # an edge dragged, or the whole block


def apply_grid_op(op):
    """
    Save one op from the grid:
      {kind: "paint", date, track, start, end, block: {label, categoryId} | null, newId}
      {kind: "upsert", entry}   (edits from the block card / right-click)
      {kind: "delete", id}
      {kind: "move", id, date, track, start, end}   (a block dragged to a new place, or its edge dragged)
      {kind: "hide_outlook", uid}     remove an Outlook occurrence from the timetable
      {kind: "detach_outlook", uid}   turn it into the user's own block (id "ol:<uid>")
      {kind: "batch", label, ops: [...]}   several of the above (a group moved, pasted or deleted):
                                     one Undo point for all of them, labelled e.g. "Moved 3 blocks"
    The day's Actual (store, "Plan locked"), each locking the day first:
      {kind: "skip", date, start, end}                    didn't happen
      {kind: "replace", date, start, end, block, newId}   did something else, or something unplanned
      {kind: "retime", date, fromStart, fromEnd, start, end, block, newId}   change times
      {kind: "confirm_day", date}                         this is what I did
      {kind: "unconfirm_day", date}                       undo that
      {kind: "add_suggestion", date, start, end, block}   one suggested sitting, added to the Plan if still free
    Painting over an Outlook event detaches it first (store.paint), so it's trimmed like any block.
    Every day an op touches is locked first if it has started, and a started day's Plan is never changed:
    such an op (from a grid drawn before the day started) is dropped; the redraw shows the Actual.
    """
    days = _op_days(op)
    if days:
        store.lock_started(min(days), max(days))
    if _touches_locked_plan(op):
        return
    if op["kind"] == "batch":
        from venato import undo
        undo.checkpoint(op.get("label") or "Changed several blocks", quiet=True)    # no bar; Cmd/Ctrl+Z undoes
        for sub in op.get("ops") or []:
            _apply(sub)
        return
    if op.get("quiet"):                          # a paste: undoable with Cmd/Ctrl+Z, without the Undo bar
        from venato import undo
        undo.checkpoint(op.get("label") or "Pasted a block", quiet=True)
    else:
        _checkpoint(op)
    _apply(op)


def _op_days(op):
    """The days an op changes."""
    if op["kind"] == "batch":
        return {d for sub in op.get("ops") or [] for d in _op_days(sub)}
    out = {op[k] for k in ("date",) if op.get(k)}
    if op["kind"] == "upsert":
        out.add(op["entry"]["date"])
    if op["kind"] in ("delete", "move") and op.get("id"):
        b = store.get_block(op["id"])
        if b:
            out.add(b["date"])
    if op["kind"] in ("hide_outlook", "detach_outlook"):
        ev = store.get_outlook(op["uid"])
        if ev:
            out.add(ev["date"])
    return out


def _touches_locked_plan(op):
    """Would this op change the Plan of a day that has started (locked)?"""
    if op["kind"] == "batch":
        return any(_touches_locked_plan(sub) for sub in op.get("ops") or [])
    started = store.day_started
    if op["kind"] in ("paint", "move") and op.get("track") == "plan" and started(op["date"]):
        return True
    if op["kind"] == "upsert" and op["entry"].get("track") == "plan" and started(op["entry"]["date"]):
        return True
    if op["kind"] in ("delete", "move"):
        b = store.get_block(op["id"])
        if b and b["track"] == "plan" and started(b["date"]):
            return True
    if op["kind"] in ("hide_outlook", "detach_outlook"):
        ev = store.get_outlook(op["uid"])
        return bool(ev and started(ev["date"]))
    return False


def _block(b):
    return {"label": b["label"], "category_id": b["categoryId"], "details": b.get("details")} if b else None


def _apply(op):
    kind = op["kind"]
    if kind == "skip":
        store.correct(op["date"], store.slot_of(op["start"]), store.slot_of(op["end"]), None)
    elif kind == "replace":
        store.correct(op["date"], store.slot_of(op["start"]), store.slot_of(op["end"]), _block(op["block"]),
                      new_id=op.get("newId"))
    elif kind == "retime":
        store.retime(op["date"], store.slot_of(op["fromStart"]), store.slot_of(op["fromEnd"]),
                     store.slot_of(op["start"]), store.slot_of(op["end"]), _block(op["block"]), new_id=op.get("newId"))
    elif kind == "confirm_day":
        store.confirm_day(op["date"])
    elif kind == "unconfirm_day":
        store.unconfirm_day(op["date"])
    elif kind == "add_suggestion":
        from venato.ui import goal_time
        goal_time.add_suggestion(op["date"], op["start"], op["end"], _block(op["block"]), new_id=op.get("newId"))
    if kind in ("skip", "replace", "retime", "confirm_day", "unconfirm_day", "add_suggestion"):
        return
    if op["kind"] == "paint":
        s, e = store.slot_of(op["start"]), store.slot_of(op["end"])
        block = op.get("block")
        if block:
            block = {"label": block["label"], "category_id": block["categoryId"], "details": block.get("details")}
        store.paint(op["date"], op["track"], s, e, block, new_id=op.get("newId"))
    elif op["kind"] == "upsert":
        e = op["entry"]
        store.upsert_blocks([{**{k: e[k] for k in ("id", "date", "track", "start", "end", "label")},
                              "category_id": e["categoryId"], "details": e.get("details") or None}])
    elif op["kind"] == "delete":
        store.delete_block(op["id"])
    elif op["kind"] == "move":                       # dragged: moved and/or resized
        store.move_block(op["id"], op["date"], op["track"], store.slot_of(op["start"]), store.slot_of(op["end"]))
    elif op["kind"] == "hide_outlook":
        store.hide_outlook(op["uid"])
    elif op["kind"] == "detach_outlook":
        store.detach_outlook(op["uid"])


def _on_ops(key):
    """Component callback: save new ops and remember them as acknowledged."""
    ops = st.session_state[key]["ops"] or []
    acked = st.session_state.setdefault("tt_acked", [])
    new_ops = [op for op in ops if op["opId"] not in acked]
    for op in new_ops:
        apply_grid_op(op)
    # Keep the list short; the grid only ever has a few ops in flight.
    st.session_state["tt_acked"] = (acked + [op["opId"] for op in new_ops])[-500:]


def _shift_week(weeks):
    """Prev/next/this-week callback (also used by sideways swipes on the grid)."""
    if weeks == 0:
        st.session_state["tt_day"] = store.local_today()
    else:
        st.session_state["tt_day"] += timedelta(weeks=weeks)


def _on_nav(key):
    """Component callback: ‹ / Today / › buttons or a sideways swipe."""
    nav = st.session_state[key]["nav"]
    if not nav:
        return
    if nav.get("date"):
        st.session_state["tt_day"] = date.fromisoformat(nav["date"])
    else:
        _shift_week(nav["dir"])


def sync_outlook(force=False):
    """
    Sync the Outlook calendar if forced or the last try was over 15 minutes ago.
    Returns True only if the imported events changed (so the page needs redrawing).
    """
    now = datetime.now()
    last = st.session_state.get("outlook_tried")
    # (a little slack so the 15-minute timer never just misses the threshold)
    if force or last is None or now - last >= SYNC_EVERY - timedelta(seconds=30):
        st.session_state["outlook_tried"] = now
        before = store.outlook_signature()
        st.session_state["outlook_status"] = outlook.sync()
        return store.outlook_signature() != before
    return False


def _on_sync(key):
    sync_outlook(force=True)


def _on_outlook_toggle(key):
    value = st.session_state[key]["outlook"] or {}
    st.session_state["tt_show_outlook"] = bool(value.get("show"))


def _sync_text():
    """'Synced 5 min ago', or an offline note. Never mentions the calendar URL."""
    if not outlook.ics_url() and not outlook.extra_calendars():
        return {"text": "No calendar connected", "error": False,
                "detail": "Connect Outlook, Google or Apple calendars in Settings → Calendar."}
    status = st.session_state.get("outlook_status") or {}
    when = outlook.ago(status.get("synced_at") or outlook.last_synced())
    if status.get("error"):
        return {"text": f"Offline · events from {when}", "error": True,
                "detail": f"Calendar sync failed: {status['error']} Showing the last synced events."}
    return {"text": f"Synced {when}", "error": False, "detail": "Calendars (read only)"}


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

def render_page():
    day = st.session_state.setdefault("tt_day", store.local_today())
    monday = store.week_start_of(day)            # the week's first day: Monday, or Sunday if chosen
    # Fit time / Categories: the same things Claude can do, by hand.
    from venato import pace
    from venato.ui import goal_time, timetable_tools
    ctx = pace.Ctx()                             # one look at the timetable for the grid, the panel and the bar
    sugg = goal_time.suggestions_for(monday, ctx)
    grid, panel = st.columns([4, 1.3], gap="medium")     # the panel stacks under the grid on narrow screens
    with grid:
        render_grid([monday + timedelta(days=i) for i in range(7)], suggestions=sugg)
    st.html("<style>.st-key-tt_panel { max-height: calc(100vh - 160px); overflow-y: auto; }</style>")   # scrolls itself, not the page
    with panel.container(key="tt_panel"):
        goal_time.planner(monday, ctx)
    # The buttons and the suggestions go below everything, so the week is the first thing you see.
    row = st.container(horizontal=True, gap="small", vertical_alignment="center", key="tt_toolbar")
    timetable_tools.toolbar(day, row)
    goal_time.suggestion_bar(monday, sugg, ctx, row)


# ---------------------------------------------------------------------------
# Home's end-of-day prompt: "Is the timetable right for today?"
# ---------------------------------------------------------------------------

def prompt_days(now=None):
    """Days to ask about: today once its last planned block has passed, and yesterday, if not confirmed
    yet and not dismissed. Never anything older (no nagging)."""
    now = now or store.local_now()
    today = store.local_today()
    gone = set(store.load_settings().get("eod_dismissed") or [])
    status = store.day_status(today - timedelta(days=1), today)
    out = []
    for day in (today, today - timedelta(days=1)):
        iso = day.isoformat()
        if iso in gone or status.get(iso, {}).get("confirmed"):
            continue
        if day == today and not store.day_ended(iso, now):
            continue
        if day < today and store.slots_gone(iso, now) < store.SLOTS:
            continue                                 # (yesterday's late night isn't over yet)
        if day < today or store.blocks_between(iso, iso) or store.outlook_between(iso, iso):
            out.append(day)
    return out


def _confirm_all(day):
    store.confirm_day(day)
    st.toast("Confirmed: that was your day", icon=":material/task_alt:")


def _review(day):
    st.session_state["tt_day"] = day
    st.session_state["tt_force_mode"] = "actual"      # once: the grid opens on the Actual
    st.session_state["page"] = "Timetable"         # the sidebar radio's key; callbacks run before it's drawn


def _dismiss(day):
    gone = list(store.load_settings().get("eod_dismissed") or [])
    store.save_settings(eod_dismissed=sorted(set(gone[-30:] + [day.isoformat()])))


def end_of_day_prompt():
    """Home: for today (once its Plan is over) and yesterday, if unconfirmed: Confirm / Review / Not now."""
    for day in prompt_days():
        when = "today" if day == store.local_today() else "yesterday"
        with st.container(border=True, key=f"eod_{day.isoformat()}"):
            row = st.container(horizontal=True, gap="small", vertical_alignment="center")   # one line: question + buttons
            row.markdown(f"**Is the timetable right for {when}?**", width="stretch",
                         help=f"Confirm {regional.long_date(day)}'s Actual is what you really did: only confirmed "
                              "days count in your stats and goals.")
            row.button("Confirm", key=f"eod_ok_{day}", type="primary", icon=":material/task_alt:",
                       on_click=_confirm_all, args=(day,), help=f"Confirm {when}'s Actual is what you did")
            row.button("Review", key=f"eod_review_{day}", icon=":material/edit_calendar:",
                       on_click=_review, args=(day,), help=f"Open {when} on the Timetable to correct it")
            row.button("Not now", key=f"eod_no_{day}", type="tertiary", on_click=_dismiss, args=(day,),
                       help="Hide this; the day stays unconfirmed")


def render_today():
    """Just today (the Home page): its Actual (the Plan as locked this morning, plus your changes). View only."""
    render_grid([store.local_today()], key="timetable_today", single=True, readonly=True)


def render_grid(days, key="timetable", single=False, readonly=False, suggestions=()):
    """Draw the grid for the given days; returns the categories and label map it used.
    Days that have started are locked first (their Plan copied into the Actual), so what's drawn is final."""
    now = store.local_now()
    store.lock_started(days[0], days[-1], now)
    status = store.day_status(days[0], days[-1])
    categories = store.load_categories()
    entries = store.blocks_between(days[0].isoformat(), days[-1].isoformat())
    label_map = store.load_label_map()
    show_outlook = st.session_state.setdefault("tt_show_outlook", True)
    events = store.outlook_between(days[0].isoformat(), days[-1].isoformat()) if show_outlook else []

    data = {
        "days": [d.isoformat() for d in days],
        "today": store.local_today().isoformat(),
        "nowMin": (lambda n: n.hour * 60 + n.minute + n.second / 60)(store.local_now()),   # Home's time line
        "groups": store.groups(),
        "categories": [
            {"id": r.id, "name": r.name, "colour": r.colour, "textColour": r.text_colour,
             "group": r.grp, "order": int(r.ord)}
            for r in categories.itertuples()
        ],
        "entries": [
            {"id": e["id"], "date": e["date"], "track": e["track"], "start": e["start"], "end": e["end"],
             "label": e["label"], "categoryId": e["category_id"], "details": e["details"]}
            for e in entries
        ],
        "labelMap": dict(zip(label_map["label"], label_map["category_id"])),
        "acked": st.session_state.get("tt_acked", []),
        "single": single,
        # The Plan / Actual switch lives in the browser (no rerun); Python only forces it once (Home's Review).
        "mode": "actual" if readonly else st.session_state.pop("tt_force_mode", None),
        "readonly": readonly,
        # Suggested sittings for hours goals that are short (dashed, in free time; click one to add it).
        "suggestions": list(suggestions),
        # Per day: the slots that have passed, locked (the day has started: its Plan is frozen), confirmed.
        "dayState": {d.isoformat(): {"gone": store.slots_gone(d, now), "locked": store.day_started(d, now),
                                     "confirmed": status.get(d.isoformat(), {}).get("confirmed", False)}
                     for d in days},
        # Outlook events (Plan; all-day ones as header chips). The user can remove or change them.
        "showOutlook": show_outlook,
        "outlook": [
            {"id": e["uid"], "date": e["date"], "start": e["start"], "end": e["end"], "title": e["title"],
             "location": e["location"], "exact": regional.times_in(e["exact"]), "description": e["description"],
             "details": store.outlook_details(e), "categoryId": store.outlook_category(e["title"])}
            for e in events if not e["all_day"]
        ],
        "outlookAllDay": [{"date": e["date"], "title": e["title"]} for e in events if e["all_day"]]
        + [{"date": d["due"], "title": f"Due: {d['title']}", "deadline": True} for d in store.deadlines()
           if days[0].isoformat() <= d["due"] <= days[-1].isoformat()],
        "sync": _sync_text(),
        "clock": regional.clock(),
        "slots": store.SLOTS,
        "firstMin": store.FIRST_MIN,
        "dateFormat": regional.date_format(),
    }
    _timetable_component(data=data, key=key,
                         on_ops_change=lambda: _on_ops(key), on_nav_change=lambda: _on_nav(key),
                         on_sync_change=lambda: _on_sync(key), on_outlook_change=lambda: _on_outlook_toggle(key))
    return categories, label_map

