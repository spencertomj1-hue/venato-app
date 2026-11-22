"""
Timetable's sleep widget (top of the side panel): what time did you wake up today, and go to bed?

Until a day has both, the panel asks. Each answer fills Sleep blocks on that day's live track (its Plan before
the day starts, its Actual after): waking fills from the start of the timetable day to the wake-up time, bed
fills from bed time to the end of the timetable day. Only free time is filled, so nothing of yours is overwritten.
A time outside the timetable day fills nothing but still counts as answered.

What's been answered is kept per day in settings.json ("sleep_times": {iso date: {"wake", "bed"}}), the last
SLEEP_DAYS days only. A Sleep block already touching the start (or end) of the day counts as answered too.
"""

from datetime import timedelta

import streamlit as st

from venato import regional
from venato import store
from venato.ui import kit

SLEEP_DAYS = 14
LABEL = "Sleep"


def sleep_category():
    """The Sleep example category's id (made if it isn't there)."""
    from venato.ui import onboarding
    return onboarding.example_category("sleep")


def _hhmm(t):
    return t if isinstance(t, str) else f"{t.hour:02d}:{t.minute:02d}"


def answered(day, now=None):
    """{"wake": bool, "bed": bool}: is each already known for this day?"""
    iso = day.isoformat()
    saved = store.load_settings().get("sleep_times", {}).get(iso, {})
    track = store.live_track(day, now)
    cats = store.load_categories()
    sleep_ids = set(cats[cats["name"].str.lower() == "sleep"]["id"])
    sleeps = [b for b in store.blocks_between(iso, iso, track)
              if b["category_id"] in sleep_ids or b["label"].strip().lower() == "sleep"]
    last = store.slot_count()
    return {"wake": "wake" in saved or any(store.slot_of(b["start"]) == 0 for b in sleeps),
            "bed": "bed" in saved or any(min(store.slot_of(b["end"]), last) == last and store.slot_of(b["start"]) < last
                                         for b in sleeps)}


def _remember(day, **times):
    keep = (day - timedelta(days=SLEEP_DAYS)).isoformat()
    all_ = {d: v for d, v in store.load_settings().get("sleep_times", {}).items() if d > keep}
    all_[day.isoformat()] = {**all_.get(day.isoformat(), {}), **times}
    store.save_settings(sleep_times=all_)


def _fill(day, s, e, now=None):
    """Paint Sleep into the free slots s..e-1 of the day's live track. Returns half-hours filled."""
    if e <= s:
        return 0
    track = store.live_track(day, now)
    store.lock_day(day, now=now)                     # a started day's Plan copied into its Actual first
    block = {"label": LABEL, "category_id": sleep_category()}
    filled = 0
    for a, b in store.free_runs(day, s, e, now):
        store.paint(day, track, a, b, block)
        filled += b - a
    return filled


def record(day, wake=None, bed=None, now=None):
    """Save a wake-up and/or bed time ("HH:MM" or a time) for `day` and fill its Sleep blocks.
    Returns the half-hours of Sleep added."""
    last, filled = store.slot_count(), 0
    if wake is not None:
        wake = _hhmm(wake)
        w = store.slot_of(wake)
        filled += _fill(day, 0, w if w <= last else 0, now)     # after the day's end: woke before it started
        _remember(day, wake=wake)
    if bed is not None:
        bed = _hhmm(bed)
        b = store.slot_of(bed)
        filled += _fill(day, b, last, now) if b < last else 0     # past the day's end: nothing to fill
        _remember(day, bed=bed)
    return filled


def _on_add(day):
    wake, bed = st.session_state.get("tt_wake"), st.session_state.get("tt_bed")
    if wake is None and bed is None:
        st.session_state["tt_sleep_note"] = "Pick a time first."
        return
    n = record(day, wake, bed)
    st.session_state["tt_sleep_note"] = (f"Added {n / 2:g} h of sleep." if n else "Saved. Nothing to fill: "
                                         "that's outside the timetable day or already taken.")
    st.session_state.pop("tt_wake", None)
    st.session_state.pop("tt_bed", None)


def render(day=None):
    """The widget, if today is missing a wake-up or bed time; otherwise just a note from the last Add."""
    day = day or store.local_today()
    note = st.session_state.pop("tt_sleep_note", None)
    known = answered(day)
    if known["wake"] and known["bed"]:
        if note:
            st.toast(note, icon=":material/bedtime:")
        return
    start, end = store.slot_time(0), store.slot_time(store.slot_count())
    with st.container(border=True, key="tt_sleep"):
        kit.subhead("Your sleep today", icon=":material/bedtime:")
        st.caption(f"Sleep fills the timetable from {regional.time(start)} to when you woke, "
                   f"and from bed time to {regional.time(end)}.")
        if not known["wake"]:
            st.time_input("Woke up at", None, step=1800, key="tt_wake")
        if not known["bed"]:
            st.time_input("Went to bed at", None, step=1800, key="tt_bed")
        st.button("Add", key="tt_sleep_add", type="primary", icon=":material/add:", on_click=_on_add, args=(day,))
        if note:
            st.caption(note)
