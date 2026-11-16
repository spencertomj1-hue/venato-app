"""
Joint calendar page: the user's week (yellow) next to their partner's (purple).

Each day has two lanes: yours on the left, theirs on the right. Events are
blocked-out time; only events with "!" in their title show their name (joint.py
applies that rule when it reads the calendars). Drawn as plain HTML: nothing to
edit here, so no component is needed.
"""

from datetime import date, datetime, timedelta
from html import escape

import streamlit as st

from venato import joint
from venato import outlook
from venato import store
from venato import system

PAGE = "Joint calendar"
HOURS = (7, 24)        # shown by default; widened when an event falls outside
HOUR_PX = 38


def _hm(minutes):
    return f"{minutes // 60 % 24:02d}:{minutes % 60:02d}"


def _shift(n):
    if n == 0:
        st.session_state["joint_week"] = joint.week_of(store.local_today())[0]
    else:
        st.session_state["joint_week"] += timedelta(days=7 * n)


def _grid(days, events, names):
    timed = [e for e in events if not e["all_day"]]
    h0 = min([HOURS[0]] + [e["start_min"] // 60 for e in timed])
    h1 = max([HOURS[1]] + [-(-e["end_min"] // 60) for e in timed])
    height = (h1 - h0) * HOUR_PX
    today = store.local_today()
    colours = {"me": joint.ME_COLOUR, "partner": joint.PARTNER_COLOUR}
    text = {"me": "#1a1a1a", "partner": "#ffffff"}

    hours = "".join(f'<div class="jc-hour" style="top:{(h - h0) * HOUR_PX}px">{h:02d}:00</div>' for h in range(h0, h1))
    lines = "".join(f'<div class="jc-line" style="top:{(h - h0) * HOUR_PX}px"></div>' for h in range(h0, h1))

    heads, chips, cols = [], [], []
    for d in days:
        iso = d.isoformat()
        heads.append(f'<div class="jc-head{" today" if d == today else ""}">{d:%a} <b>{d.day}</b></div>')
        day_chips = "".join(
            f'<span class="jc-chip" style="background:{colours[e["who"]]};color:{text[e["who"]]}" '
            f'title="{escape(names[e["who"]])}: {escape(e["title"] or "busy all day")}">{escape(e["title"] or "All day")}</span>'
            for e in events if e["all_day"] and e["date"] == iso)
        chips.append(f'<div class="jc-chips">{day_chips}</div>')
        blocks = []
        for e in timed:
            if e["date"] != iso:
                continue
            top = (e["start_min"] - h0 * 60) / 60 * HOUR_PX
            h = max((e["end_min"] - e["start_min"]) / 60 * HOUR_PX, 6)
            when = f"{_hm(e['start_min'])}–{_hm(e['end_min'])}"
            label = escape(e["title"]) if e["title"] else ""
            tip = f"{names[e['who']]} · {when}" + (f" · {e['title']}" if e["title"] else " · busy")
            blocks.append(
                f'<div class="jc-ev {e["who"]}" style="top:{top:.1f}px;height:{h - 2:.1f}px;'
                f'background:{colours[e["who"]]};color:{text[e["who"]]}" title="{escape(tip)}">'
                + (f'<b>{label}</b>' if label else "") + (f'<span>{when}</span>' if label and h > 34 else "")
                + "</div>")
        cols.append(f'<div class="jc-day{" today" if d == today else ""}" style="height:{height}px">'
                    f'{lines}{"".join(blocks)}</div>')

    return f"""<style>
      .jc {{ display: grid; grid-template-columns: 46px repeat(7, minmax(0, 1fr)); font-size: .8rem; }}
      .jc-head {{ text-align: center; padding: 4px 0; opacity: .8; }}
      .jc-head.today b {{ background: #ff4b4b; color: #fff; border-radius: 999px; padding: 0 6px; }}
      .jc-chips {{ display: flex; flex-direction: column; gap: 2px; padding: 0 2px 4px; min-height: 4px; }}
      .jc-chip {{ border-radius: 4px; padding: 0 5px; font-size: .72rem; white-space: nowrap; overflow: hidden;
                  text-overflow: ellipsis; }}
      .jc-times {{ position: relative; }}
      .jc-hour {{ position: absolute; right: 6px; transform: translateY(-50%); font-size: .7rem; opacity: .55; }}
      .jc-hour:first-child {{ transform: none; }}
      .jc-day {{ position: relative; border-left: 1px solid rgba(128,128,128,.25); }}
      .jc-day.today {{ background: rgba(128,128,128,.06); }}
      .jc-line {{ position: absolute; left: 0; right: 0; border-top: 1px solid rgba(128,128,128,.15); }}
      .jc-ev {{ position: absolute; border-radius: 5px; padding: 2px 5px; overflow: hidden; box-sizing: border-box;
                line-height: 1.25; font-size: .74rem; }}
      .jc-ev.me {{ left: 2px; right: calc(50% + 1px); }}
      .jc-ev.partner {{ left: calc(50% + 1px); right: 2px; }}
      .jc-ev b {{ display: block; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
      .jc-ev span {{ opacity: .8; font-size: .68rem; }}
      .jc-key {{ display: flex; gap: 16px; align-items: center; margin: 2px 0 10px; font-size: .85rem; }}
      .jc-key i {{ display: inline-block; width: 12px; height: 12px; border-radius: 3px; margin-right: 6px;
                   vertical-align: -1px; }}
    </style>
    <div class="jc-key">
      <span><i style="background:{joint.ME_COLOUR}"></i>{escape(names["me"])} (left)</span>
      <span><i style="background:{joint.PARTNER_COLOUR}"></i>{escape(names["partner"])} (right)</span>
      <span style="opacity:.6">Only events with “!” in their title show their name.</span>
    </div>
    <div class="jc">
      <div></div>{"".join(heads)}
      <div></div>{"".join(chips)}
      <div class="jc-times" style="height:{height}px">{hours}</div>{"".join(cols)}
    </div>"""


def _setup(connected):
    name = joint.partner_name()
    st.markdown(
        "**How to share a calendar.** In Outlook on the web: **Settings → Calendar → Shared calendars → "
        "Publish a calendar**, pick the calendar and **Can view all details** (or **titles and locations**), "
        "then **Publish** and copy the **ICS** link. (Google Calendar: Settings → your calendar → *Secret address "
        "in iCal format*.)\n\n"
        f"Only times are kept from {escape(name if connected else 'their')} calendar, plus the titles of events with "
        f"**!** in them. The link is kept in your {system.SECRET_STORE}, never in a file."
    )
    st.caption("If they publish with \"Can view when I'm busy\" only, it still works, but no titles come through, "
               "even with “!”.")
    with st.form("joint_connect", border=False, clear_on_submit=True):
        new_name = st.text_input("Their name", value=name if connected else "", placeholder="e.g. Nina")
        link = st.text_input("Their calendar's ICS link", type="password", placeholder="https://outlook.office365.com/…")
        if st.form_submit_button("Connect" if not connected else "Replace link", type="primary"):
            try:
                count = joint.connect(joint.check_link(link), new_name)
                st.session_state["joint_msg"] = ("ok", f"Connected: {count} events in the next 8 weeks.")
            except outlook.LinkError as e:
                st.session_state["joint_msg"] = ("error", str(e))
            except outlook.SyncError as e:
                st.session_state["joint_msg"] = ("error", outlook.friendly(e).replace("Outlook", "the calendar"))
            st.rerun()
    if connected and st.button("Disconnect", icon=":material/link_off:"):
        joint.disconnect()
        st.rerun()


def render_page():
    st.header("Joint calendar")
    connected = bool(joint.partner_url())
    msg = st.session_state.pop("joint_msg", None)
    if msg:
        (st.success if msg[0] == "ok" else st.error)(msg[1])

    if not connected:
        st.write("See your week next to your partner's: you in yellow, them in purple. Events are just "
                 "blocked-out time, unless the event's title has a **!** in it.")
        _setup(False)
        return

    error = joint.refresh_partner()
    joint.refresh_mine()
    if not outlook.ics_url():
        st.info("Connect your own Outlook calendar (Settings → Calendar) to see your events here too.",
                icon=":material/info:")

    sess = st.session_state
    sess.setdefault("joint_week", joint.week_of(store.local_today())[0])
    first = sess["joint_week"]
    days = [first + timedelta(days=i) for i in range(7)]

    title, nav, sync = st.columns([4, 3, 2], vertical_alignment="center")
    last = days[-1]
    title.subheader(f"{first.day} {first:%b} – {last.day} {last:%b %Y}" if first.month != last.month
                    else f"{first.day} – {last.day} {last:%B %Y}")
    a, b, c = nav.columns(3)
    a.button("‹", key="jw_prev", on_click=_shift, args=(-1,), width="stretch", help="Previous week")
    b.button("Today", key="jw_today", on_click=_shift, args=(0,), width="stretch")
    c.button("›", key="jw_next", on_click=_shift, args=(1,), width="stretch", help="Next week")
    if sync.button("", icon=":material/sync:", key="jw_sync", help=f"Refresh {joint.partner_name()}'s calendar"):
        error = joint.refresh_partner(force=True)
        if outlook.ics_url():
            outlook.sync()
            joint.refresh_mine()
    if error:
        st.warning(error, icon=":material/cloud_off:")
    synced = joint.last_partner_sync()
    sync.caption(f"Updated {outlook.ago(synced)}")

    names = {"me": "You", "partner": joint.partner_name()}
    st.html(_grid(days, joint.events_for_week(first), names))

    with st.expander(f"{joint.partner_name()}'s calendar link", icon=":material/link:"):
        _setup(True)
