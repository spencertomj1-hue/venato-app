"""The Involvement page (organisations with roles, duties and goals; the log; events and tickets)
and its Home widget. The data is in venato/blocks/involvement.py."""

from datetime import timedelta
from html import escape

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from venato import store
from venato import undo
from venato.blocks import involvement as inv
from venato.ui import kit

KIND_ICON = {"Society": ":material/groups:", "Club": ":material/sports_handball:",
             "Sports team": ":material/rowing:", "Faith": ":material/church:", "Charity": ":material/volunteer_activism:",
             "Volunteering": ":material/handshake:", "Work": ":material/work:", "Other": ":material/diversity_3:"}


def _err(fn):
    try:
        fn()
        st.rerun()
    except inv.InvError as e:
        st.error(str(e))


def _ticket_colour(t):
    good, _ = kit.good_bad()
    return {"Need to buy": kit.amber(), "Bought": good}.get(t, "#8A8F9C")


# --- Goals ---

def _goal_text(g, p):
    if g["unit"] == "money":
        return f"{inv._money(p['have'])} of {inv._money(g['target'])}"
    return f"{p['have']:g} of {g['target']:g} {g['unit']}"


def _goal_rows(gs, prefix, colour):
    good, _ = kit.good_bad()
    for g in gs:
        p = inv.goal_progress(g)
        x, y = st.columns([12, 1], vertical_alignment="center")
        with x:
            label = g["text"] + (f" · by {store.fmt_day(store._as_date(g['deadline']), '%-d %b')}" if g["deadline"] else "")
            done = st.checkbox(label, bool(g["done"]), key=f"{prefix}_gd_{g['id']}")
            if done != bool(g["done"]):
                inv.set_goal_done(g["id"], done)
                st.rerun()
            if p:
                kit.bars([{"label": "", "frac": p["pct"] / 100, "colour": good if p["pct"] >= 100 else colour,
                           "value": _goal_text(g, p)}])
        if y.button("", icon=":material/close:", key=f"{prefix}_gx_{g['id']}", help="Delete goal", type="tertiary"):
            inv.delete_goal(g["id"])
            st.rerun()


def _goal_form(org_id, key):
    with st.form(key, clear_on_submit=True, border=False):
        text = st.text_input("Goal", placeholder="e.g. 50 volunteering hours this year")
        a, b, c = st.columns([1, 1, 2], vertical_alignment="bottom")
        target = a.number_input("Target", 0.0, 1_000_000.0, None)
        unit = b.selectbox("Unit", inv.UNITS)
        deadline = c.date_input("By", None)
        if st.form_submit_button("Add goal", icon=":material/add:", type="primary"):
            _err(lambda: inv.add_goal(org_id, text, target, unit if target else None, deadline))


# --- Organisations ---

def _org_edit(o):
    x, y = st.columns(2)
    role = x.text_input("Your role", o["role"] or "", key=f"inv_r_{o['id']}")
    kind = y.selectbox("Kind", inv.KINDS, inv.KINDS.index(o["kind"]) if o["kind"] in inv.KINDS else len(inv.KINDS) - 1,
                       key=f"inv_k_{o['id']}")
    duties = st.text_area("What you do for them", o["duties"] or "", key=f"inv_du_{o['id']}", height=80)
    active = st.toggle("Still involved", bool(o["active"]), key=f"inv_a_{o['id']}")
    new = {"role": role.strip() or None, "kind": kind, "duties": duties.strip() or None, "active": int(active)}
    if any(new[k] != o[k] for k in new):
        inv.update_org(o["id"], **new)
        st.rerun()
    with st.popover("Add a goal", icon=":material/flag:"):
        _goal_form(o["id"], f"inv_gf_{o['id']}")
    with st.popover(f"Delete {o['name']}", icon=":material/delete:"):
        st.warning(f"Delete {o['name']}, its goals and its log? (Undo can bring it back.)")
        if st.button("Delete", key=f"inv_del_{o['id']}", type="primary"):
            undo.checkpoint(f"Deleted {o['name']}")
            inv.delete_org(o["id"])
            st.rerun()


def _org_card(o, today, colour):
    year = inv.totals(today.replace(month=1, day=1), today, o["id"])
    with st.container(border=True, height="stretch"):
        st.markdown(f"{KIND_ICON.get(o['kind'], ':material/diversity_3:')} **{escape(o['name'])}**")
        kit.pills([(o["kind"], colour)] + ([(o["role"], "#8A8F9C")] if o["role"] else [])
                  + ([] if o["active"] else [("Past", "#8A8F9C")]))
        bits = [f"{year['hours']:g} h this year", f"{year['count']} entr{'y' if year['count'] == 1 else 'ies'}"] \
            + ([f"{inv._money(year['donated'])} donated"] if year["donated"] else [])
        st.caption(" · ".join(bits))
        if o["duties"]:
            st.caption(o["duties"])
        gs = inv.goals(o["id"])
        if gs:
            _goal_rows(gs, f"inv_o{o['id']}", colour)
        recent = inv.entries(org_id=o["id"])[:3]
        if recent:
            st.caption("Recent: " + " · ".join(f"{store.fmt_day(store._as_date(r['date']), '%-d %b')} {r['kind'].lower()}"
                                               + (f" {r['hours']:g} h" if r["hours"] else "") for r in recent))
        if st.toggle("Edit", key=f"inv_edit_{o['id']}"):
            _org_edit(o)


def _stats(today):
    year = inv.totals(today.replace(month=1, day=1), today)
    month = inv.totals(today - timedelta(days=29), today)
    up = inv.upcoming(30)
    to_buy = sum(1 for e in up if e["ticket"] == "Need to buy")
    kit.stats([
        {"label": "Hours this year", "value": f"{year['hours']:g}",
         "delta": f"{month['hours']:g} h in the last 30 days", "delta_color": "off", "delta_arrow": "off"},
        {"label": "Volunteering this year", "value": f"{year['volunteering']:g} h"},
        {"label": "Events in the next 30 days", "value": str(len(up)),
         "delta": f"{to_buy} ticket{'s' * (to_buy != 1)} to buy" if to_buy else None, "delta_color": "off",
         "delta_arrow": "off"},
        {"label": "Donated this year", "value": inv._money(year["donated"])},
    ])


def _orgs(today):
    os_ = inv.orgs()
    colours = kit.colours(inv.KINDS)
    for i in range(0, len(os_), 2):
        cols = st.columns(2)
        for col, o in zip(cols, os_[i:i + 2]):
            with col:
                _org_card(o, today, colours.get(o["kind"], kit.PALETTE[0]))
    if not os_:
        kit.empty("No organisations yet: add the societies, clubs and causes you're part of.", ":material/groups:")
    a, b = st.columns(2)
    with a, kit.card("Overall goals", "Goals that aren't tied to one organisation."):
        loose = [g for g in inv.goals() if not g["org_id"]]
        if loose:
            _goal_rows(loose, "inv_all", kit.PALETTE[0])
        with st.popover("Add a goal", icon=":material/flag:"):
            _goal_form(None, "inv_gf_all")
    with b, kit.card("Add an organisation"):
        with st.form("inv_new", clear_on_submit=True, border=False):
            name = st.text_input("Name", placeholder="e.g. Hiking Society")
            x, y = st.columns(2)
            kind = x.selectbox("Kind", inv.KINDS)
            role = y.text_input("Your role", placeholder="e.g. Treasurer")
            duties = st.text_input("What you do for them")
            if st.form_submit_button("Add", icon=":material/add:", type="primary"):
                _err(lambda: inv.add_org(name, kind, role, duties))


# --- Log ---

def _log_chart(today):
    first = today - timedelta(weeks=12) - timedelta(days=today.weekday())
    rows = [r for r in inv.entries(first, today) if r["hours"]]
    if not rows:
        kit.empty("Log some hours to see them by week.", ":material/bar_chart:")
        return
    df = pd.DataFrame([{"week": store.week_start_of(store._as_date(r["date"])), "org": r["org"] or "Other",
                        "hours": r["hours"]} for r in rows])
    df = df.groupby(["week", "org"], as_index=False)["hours"].sum()
    colours = kit.colours(sorted(df["org"].unique()))
    fig = go.Figure()
    for org, part in df.groupby("org"):
        fig.add_bar(x=pd.to_datetime(part["week"]), y=part["hours"], name=org, marker_color=colours[org],
                    hovertemplate=f"{org}: " + "%{y:g} h<extra>week of %{x|%-d %b}</extra>")
    fig.update_layout(barmode="stack")
    fig.update_xaxes(tickformat="%-d %b")
    fig.update_yaxes(ticksuffix=" h")
    kit.chart(fig, "inv_log_chart", 240, legend=True)


def _log(today):
    names = [o["name"] for o in inv.orgs(True)]
    a, b = st.columns([2, 3])
    with a, kit.card("Log something"):
        with st.form("inv_log", clear_on_submit=True, border=False):
            x, y = st.columns(2)
            kind = x.selectbox("What", inv.ACTIVITIES)
            day = y.date_input("Date", today, max_value=today)
            org = st.selectbox("Organisation", ["(none)"] + names)
            title = st.text_input("Note", placeholder="e.g. Food bank shift / Sunday service")
            x, y = st.columns(2)
            hours = x.number_input("Hours", 0.0, 24.0, None, 0.5)
            amount = y.number_input("Amount", 0.0, 1_000_000.0, None, 1.0, help="For donations")
            if st.form_submit_button("Log it", icon=":material/add:", type="primary"):
                _err(lambda: inv.log(kind, None if org == "(none)" else org, hours, amount, title, day))
    with b, kit.card("Hours per week"):
        _log_chart(today)
    with kit.card("The last 90 days", stretch=False):
        rows = inv.entries(today - timedelta(days=89), today)
        if not rows:
            kit.empty("Nothing logged yet.")
        colours = kit.colours(inv.ACTIVITIES)
        for r in rows:
            x, y, z, w = st.columns([1.2, 1.4, 6, 0.5], vertical_alignment="center")
            x.markdown(f":gray[{store.fmt_day(store._as_date(r['date']), '%a %-d %b')}]")
            with y:
                kit.pills([(r["kind"], colours.get(r["kind"], kit.PALETTE[0]))])
            bits = ([f"**{escape(r['org'])}**"] if r["org"] else []) + ([escape(r["title"])] if r["title"] else []) \
                + ([f"{r['hours']:g} h"] if r["hours"] else []) + ([inv._money(r["amount"])] if r["amount"] else [])
            z.markdown(" · ".join(bits) or ":gray[(no details)]")
            if w.button("", icon=":material/close:", key=f"inv_ld_{r['id']}", help="Remove", type="tertiary"):
                inv.delete_entry(r["id"])
                st.rerun()


# --- Events ---

def _event_card(e, today):
    day = store._as_date(e["date"])
    past = e["date"] < today.isoformat()
    with st.container(border=True, height="stretch"):
        when = ("Today" if day == today else f"{day:%A}") + (f" · {e['start']}" if e["start"] else "")
        kit.html(f"<div style='display:flex;gap:12px;align-items:center'>{kit.date_badge(day)}<div>"
                 f"<b>{escape(e['title'])}</b><br><span style='opacity:.7;font-size:.85rem'>{escape(when)}"
                 f"{' · ' + escape(e['org']) if e['org'] else ''}</span></div></div>")
        details = [x for x in (e["location"], inv._money(e["price"]) if e["price"] else None) if x]
        if details:
            st.caption(" · ".join(details))
        x, y = st.columns([3, 2], vertical_alignment="center")
        with x:
            kit.pills([(e["ticket"] if e["ticket"] != "Not needed" else "No ticket needed",
                        _ticket_colour(e["ticket"]))])
        with y.popover("Ticket", icon=":material/confirmation_number:", width="stretch"):
            t = st.radio("Ticket", inv.TICKETS, inv.TICKETS.index(e["ticket"]), key=f"inv_t_{e['id']}",
                         label_visibility="collapsed")
            if t != e["ticket"]:
                inv.update_event(e["id"], ticket=t)
                st.rerun()
        x, y, z = st.columns(3)
        if e["url"]:
            x.link_button("Link", e["url"], icon=":material/open_in_new:", width="stretch")
        if past and y.button("I went", key=f"inv_went_{e['id']}", icon=":material/check:", width="stretch"):
            inv.attended(e["id"])
            inv.delete_event(e["id"])
            st.rerun()
        if z.button("", key=f"inv_ed_{e['id']}", icon=":material/delete:", help="Delete", width="stretch",
                    type="tertiary"):
            inv.delete_event(e["id"])
            st.rerun()


def _events(today):
    names = [o["name"] for o in inv.orgs(True)]
    ev = inv.events(today - timedelta(days=14), today + timedelta(days=365))
    with st.expander("Add an event", icon=":material/add:", expanded=not ev):
        with st.form("inv_ev", clear_on_submit=True, border=False):
            a, b, c, d = st.columns([3, 2, 1, 2])
            title = a.text_input("Event")
            day = b.date_input("Date", today)
            start = c.text_input("Time", placeholder="19:30")
            org = d.selectbox("Organisation", ["(none)"] + names)
            a, b, c, d = st.columns([2, 2, 1, 3])
            loc = a.text_input("Where")
            ticket = b.selectbox("Ticket", inv.TICKETS)
            price = c.number_input("Price", 0.0, 100_000.0, None)
            url = d.text_input("Link", placeholder="https://")
            if st.form_submit_button("Add event", type="primary"):
                _err(lambda: inv.add_event(title, day, None if org == "(none)" else org, start or None, loc, ticket,
                                           price, url))
    if not ev:
        kit.empty("No events coming up.", ":material/event:")
    cols = st.columns(3)
    for i, e in enumerate(ev):
        with cols[i % 3]:
            _event_card(e, today)


def render_page():
    st.title("Involvement")
    today = store.local_today()
    _stats(today)
    tabs = st.tabs(["Organisations", "Log", "Events"])
    with tabs[0]:
        _orgs(today)
    with tabs[1]:
        _log(today)
    with tabs[2]:
        _events(today)


def render_home():
    st.markdown("**Involvement**")
    today = store.local_today()
    bits = [f"{e['title']} {store.fmt_day(store._as_date(e['date']), '%a %-d %b')}" + (" (ticket to buy)" if e["ticket"] == "Need to buy" else "")
            for e in inv.upcoming(14)[:3]]
    t = inv.totals(today - timedelta(days=29), today)
    if t["volunteering"]:
        bits.append(f"{t['volunteering']:g} h volunteering this month")
    open_goals = inv.goals(open_only=True)
    if open_goals:
        bits.append(f"{len(open_goals)} open goal{'s' if len(open_goals) != 1 else ''}")
    st.caption(" · ".join(bits) or "Nothing coming up.")
