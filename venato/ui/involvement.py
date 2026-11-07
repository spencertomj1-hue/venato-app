"""The Involvement page (organisations with roles, duties and goals; the log; events and tickets)
and its Home widget. The data is in venato/blocks/involvement.py."""

from datetime import timedelta

import streamlit as st

from venato import store
from venato import undo
from venato.blocks import involvement as inv


def _err(fn):
    try:
        fn()
        st.rerun()
    except inv.InvError as e:
        st.error(str(e))


def _goal_rows(gs, prefix):
    for g in gs:
        p = inv.goal_progress(g)
        x, y = st.columns([8, 1], vertical_alignment="center")
        label = g["text"] + (f" · by {store.fmt_day(store._as_date(g['deadline']), '%-d %b')}" if g["deadline"] else "")
        done = x.checkbox(label, bool(g["done"]), key=f"{prefix}_gd_{g['id']}")
        if done != bool(g["done"]):
            inv.set_goal_done(g["id"], done)
            st.rerun()
        if p:
            unit = inv._money(p["have"]) + " of " + inv._money(g["target"]) if g["unit"] == "money" \
                else f"{p['have']:g} of {g['target']:g} {g['unit']}"
            x.progress(p["pct"] / 100, text=unit)
        if y.button("", icon=":material/close:", key=f"{prefix}_gx_{g['id']}", help="Delete goal"):
            inv.delete_goal(g["id"])
            st.rerun()


def _goal_form(org_id, key):
    with st.form(key, clear_on_submit=True, border=False):
        a, b, c, d = st.columns([4, 1, 1, 2], vertical_alignment="bottom")
        text = a.text_input("New goal", placeholder="e.g. 50 volunteering hours this year")
        target = b.number_input("Target", 0.0, 1_000_000.0, None)
        unit = c.selectbox("Unit", inv.UNITS)
        deadline = d.date_input("By", None)
        if st.form_submit_button("Add goal"):
            _err(lambda: inv.add_goal(org_id, text, target, unit if target else None, deadline))


def _org_card(o, today):
    year = inv.totals(today.replace(month=1, day=1), today, o["id"])
    head = f"**{o['name']}** · {o['kind']}" + (f" · {o['role']}" if o["role"] else "") + ("" if o["active"] else " · past")
    with st.expander(head, expanded=False):
        a, b, c = st.columns(3)
        a.metric("Hours this year", f"{year['hours']:g}")
        b.metric("Entries this year", year["count"])
        if year["donated"]:
            c.metric("Donated this year", inv._money(year["donated"]))
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
        st.markdown("**Goals**")
        _goal_rows(inv.goals(o["id"]), f"inv_o{o['id']}")
        _goal_form(o["id"], f"inv_gf_{o['id']}")
        recent = inv.entries(org_id=o["id"])[:5]
        if recent:
            st.caption("Recent: " + " · ".join(f"{store.fmt_day(store._as_date(r['date']), '%-d %b')} {r['kind'].lower()}"
                                               + (f" {r['hours']:g} h" if r["hours"] else "") for r in recent))
        if st.button(f"Delete {o['name']}", key=f"inv_del_{o['id']}", icon=":material/delete:"):
            undo.checkpoint(f"Deleted {o['name']}")
            inv.delete_org(o["id"])
            st.rerun()


def _orgs(today):
    os_ = inv.orgs()
    for o in os_:
        _org_card(o, today)
    with st.expander("Add an organisation", icon=":material/add:", expanded=not os_):
        with st.form("inv_new", clear_on_submit=True, border=False):
            a, b, c = st.columns([3, 2, 2])
            name = a.text_input("Name", placeholder="e.g. Hiking Society")
            kind = b.selectbox("Kind", inv.KINDS)
            role = c.text_input("Your role", placeholder="e.g. Treasurer")
            duties = st.text_input("What you do for them")
            if st.form_submit_button("Add"):
                _err(lambda: inv.add_org(name, kind, role, duties))
    loose = [g for g in inv.goals() if not g["org_id"]]
    st.markdown("**Overall goals**")
    _goal_rows(loose, "inv_all")
    _goal_form(None, "inv_gf_all")


def _log(today):
    names = [o["name"] for o in inv.orgs(True)]
    with st.form("inv_log", clear_on_submit=True, border=False):
        a, b, c = st.columns([2, 3, 2])
        kind = a.selectbox("What", inv.ACTIVITIES)
        org = b.selectbox("Organisation", ["(none)"] + names)
        day = c.date_input("Date", today, max_value=today)
        a, b, c = st.columns([3, 1, 1], vertical_alignment="bottom")
        title = a.text_input("Note", placeholder="e.g. Food bank shift / Sunday service")
        hours = b.number_input("Hours", 0.0, 24.0, None, 0.5)
        amount = c.number_input("Amount", 0.0, 1_000_000.0, None, 1.0, help="For donations")
        if st.form_submit_button("Log it", icon=":material/add:"):
            _err(lambda: inv.log(kind, None if org == "(none)" else org, hours, amount, title, day))
    first = today - timedelta(days=89)
    t = inv.totals(today - timedelta(days=29), today)
    a, b, c, d = st.columns(4)
    a.metric("Volunteering (30 days)", f"{t['volunteering']:g} h")
    b.metric("Practice (30 days)", t["practice"])
    c.metric("Events (30 days)", t["events"])
    d.metric("Donated (30 days)", inv._money(t["donated"]))
    for r in inv.entries(first, today):
        x, y = st.columns([10, 1], vertical_alignment="center")
        bits = [f"{store.fmt_day(store._as_date(r['date']), '%a %-d %b')}", r["kind"]] + ([r["org"]] if r["org"] else []) \
            + ([r["title"]] if r["title"] else []) + ([f"{r['hours']:g} h"] if r["hours"] else []) \
            + ([inv._money(r["amount"])] if r["amount"] else [])
        x.markdown(" · ".join(bits))
        if y.button("", icon=":material/close:", key=f"inv_ld_{r['id']}", help="Remove"):
            inv.delete_entry(r["id"])
            st.rerun()


def _events(today):
    names = [o["name"] for o in inv.orgs(True)]
    ev = inv.events(today - timedelta(days=14), today + timedelta(days=365))
    for e in ev:
        past = e["date"] < today.isoformat()
        with st.container(border=True):
            a, b, c = st.columns([4, 2, 2], vertical_alignment="center")
            a.markdown(f"**{e['title']}**" + (f" · {e['org']}" if e["org"] else "") + "  \n"
                       + f"{store.fmt_day(store._as_date(e['date']), '%a %-d %b')}" + (f" {e['start']}" if e["start"] else "")
                       + (f" · {e['location']}" if e["location"] else "")
                       + (f" · {inv._money(e['price'])}" if e["price"] else "")
                       + (f" · [link]({e['url']})" if e["url"] else ""))
            t = b.selectbox("Ticket", inv.TICKETS, inv.TICKETS.index(e["ticket"]), key=f"inv_t_{e['id']}",
                            label_visibility="collapsed")
            if t != e["ticket"]:
                inv.update_event(e["id"], ticket=t)
                st.rerun()
            if past and c.button("I went", key=f"inv_went_{e['id']}", icon=":material/check:"):
                inv.attended(e["id"])
                inv.delete_event(e["id"])
                st.rerun()
            if c.button("Delete", key=f"inv_ed_{e['id']}", icon=":material/delete:"):
                inv.delete_event(e["id"])
                st.rerun()
    if not ev:
        st.caption("No events coming up.")
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
            if st.form_submit_button("Add event"):
                _err(lambda: inv.add_event(title, day, None if org == "(none)" else org, start or None, loc, ticket,
                                           price, url))


def render_page():
    st.title("Involvement")
    today = store.local_today()
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
