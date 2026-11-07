"""The Cut down page (a card per tracker: today vs limit, one-tap presets, streaks, a chart,
settings) and its Home widget. The data is in venato/blocks/cutdown.py."""

from datetime import timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from venato import store
from venato import undo
from venato.blocks import cutdown as cd


def _money(x):
    return f"{x:,.2f}"


def _card(t, today, day):
    s = cd.status(t, today)
    shown = cd.day_total(t["id"], day)
    with st.container(border=True):
        a, b = st.columns([3, 2])
        a.markdown(f"### {t['name']}")
        limit = t["daily_limit"]
        if t["goal"] == "quit":
            b.metric("Days free", s["days_free"])
        elif limit is not None:
            b.metric("Days under the limit", s.get("streak", 0))
        verdict = ""
        if limit is not None:
            verdict = " · over the limit" if shown > limit else f" · {max(0, limit - shown):g} left"
        a.markdown(f"**{shown:g} {t['unit']}**{' today' if day == today else ''}"
                   + (f" / {limit:g}" if limit is not None else "") + verdict)
        if limit:
            a.progress(min(1.0, shown / limit))
        bits = []
        if t["weekly_limit"] is not None:
            bits.append(f"this week {s['week']:g} / {t['weekly_limit']:g} {t['unit']}" + (" (over)" if s["over_week"] else ""))
        if s.get("spent_month"):
            bits.append(f"spent this month {_money(s['spent_month'])}")
        if s.get("saved"):
            bits.append(f"saved since quitting {_money(s['saved'])}")
        if bits:
            st.caption(" · ".join(bits))

        ps = cd.presets(t["id"])
        if t["mode"] == "total":
            with st.form(f"cd_total_{t['id']}_{day}", border=False):
                x, y = st.columns([2, 1], vertical_alignment="bottom")
                val = x.number_input(f"Total {t['unit']} for the day", 0.0, 24.0 if t["unit"] == "hours" else 100000.0,
                                     float(shown), 0.25, key=f"cd_tv_{t['id']}_{day}")
                if y.form_submit_button("Save", width="stretch"):
                    cd.log(t["id"], val, day)
                    st.rerun()
        else:
            if ps:
                cols = st.columns(min(len(ps), 5))
                for i, p in enumerate(ps):
                    if cols[i % len(cols)].button(f"+ {p['name']}", key=f"cd_p_{p['id']}_{day}",
                                                  help=f"{p['amount']:g} {t['unit']}", width="stretch"):
                        cd.log(t["id"], p["amount"], day, f"1 × {p['name']}")
                        st.rerun()
            with st.form(f"cd_amt_{t['id']}_{day}", border=False, clear_on_submit=True):
                x, y = st.columns([2, 1], vertical_alignment="bottom")
                val = x.number_input(f"Other amount ({t['unit']})", 0.0, 100000.0, None, key=f"cd_av_{t['id']}_{day}")
                if y.form_submit_button("Add", width="stretch") and val:
                    cd.log(t["id"], val, day)
                    st.rerun()
            rows = cd.entries(t["id"], day)
            if rows:
                with st.expander(f"{len(rows)} logged"):
                    for e in rows:
                        x, y = st.columns([6, 1], vertical_alignment="center")
                        x.markdown(f"{e['time'] or ''} {e['what'] or ''} · {e['amount']:g} {t['unit']}")
                        if y.button("", icon=":material/close:", key=f"cd_del_{e['id']}", help="Remove"):
                            cd.delete_entry(e["id"])
                            st.rerun()

        data = cd.daily(t["id"], today - timedelta(days=29), today)
        if data:
            df = pd.DataFrame([{"date": d, "amount": v} for d, v in data.items()])
            df["date"] = pd.to_datetime(df["date"])
            fig = px.bar(df, x="date", y="amount", height=200, labels={"amount": t["unit"], "date": ""})
            if limit:
                fig.add_hline(y=limit, line_dash="dot")
            fig.update_layout(margin=dict(l=0, r=0, t=10, b=0))
            fig.update_xaxes(tickformat="%-d %b")
            st.plotly_chart(fig, width="stretch", key=f"cd_chart_{t['id']}")

        with st.expander("Settings", icon=":material/tune:"):
            x, y, z, w = st.columns(4)
            dl = x.number_input("Daily limit", 0.0, 100000.0, t["daily_limit"], key=f"cd_dl_{t['id']}",
                                help="Empty: no daily limit")
            wl = y.number_input("Weekly limit", 0.0, 100000.0, t["weekly_limit"], key=f"cd_wl_{t['id']}")
            goal = z.selectbox("Goal", ["reduce", "quit"], index=0 if t["goal"] == "reduce" else 1, key=f"cd_goal_{t['id']}")
            cost = w.number_input(f"Cost per {t['unit'].rstrip('s')}", 0.0, 10000.0, t["cost"], key=f"cd_cost_{t['id']}")
            base = None
            if goal == "quit":
                base = st.number_input(f"How many {t['unit']} a day before quitting (for money saved)", 0.0, 100000.0,
                                       t["baseline"], key=f"cd_base_{t['id']}")
            new = {"daily_limit": dl, "weekly_limit": wl, "goal": goal, "cost": cost}
            if goal == "quit":
                new["baseline"] = base
            if any(new[k] != t[k] for k in new):
                try:
                    cd.update_tracker(t["id"], **new)
                    st.rerun()
                except cd.CutError as e:
                    st.error(str(e))
            if t["mode"] == "add":
                st.caption("Presets: " + (", ".join(f"{p['name']} = {p['amount']:g} {t['unit']}" for p in ps) or "none"))
                with st.form(f"cd_padd_{t['id']}", clear_on_submit=True, border=False):
                    x, y, z = st.columns([3, 2, 1], vertical_alignment="bottom")
                    pname = x.text_input("New preset", key=f"cd_pn_{t['id']}", placeholder="e.g. Flat white")
                    pamt = y.number_input(f"Amount ({t['unit']})", 0.0, 100000.0, None, key=f"cd_pa_{t['id']}")
                    if z.form_submit_button("Add"):
                        try:
                            cd.save_preset(t["id"], pname, pamt or 0)
                            st.rerun()
                        except cd.CutError as e:
                            st.error(str(e))
                if ps:
                    gone = st.selectbox("Remove a preset", [""] + [p["name"] for p in ps], key=f"cd_prm_{t['id']}")
                    if gone:
                        cd.delete_preset(next(p["id"] for p in ps if p["name"] == gone))
                        st.rerun()
            if st.button(f"Delete the {t['name']} tracker", key=f"cd_tdel_{t['id']}", icon=":material/delete:"):
                undo.checkpoint(f"Deleted the {t['name']} tracker")
                cd.delete_tracker(t["id"])
                st.rerun()


def render_page():
    st.title("Cut down")
    today = store.local_today()
    day = st.date_input("Day", today, key="cd_day", max_value=today)
    ts = cd.trackers()
    cols = st.columns(2, gap="medium")
    for i, t in enumerate(ts):
        with cols[i % 2]:
            _card(t, today, day)
    with st.expander("Track something else", icon=":material/add:"):
        with st.form("cd_new", clear_on_submit=True):
            a, b, c = st.columns(3)
            name = a.text_input("Name", placeholder="e.g. Sugar")
            unit = b.text_input("Unit", placeholder="e.g. g")
            goal = c.selectbox("Goal", ["reduce", "quit"])
            a, b, c = st.columns(3)
            daily = a.number_input("Daily limit", 0.0, 100000.0, None)
            weekly = b.number_input("Weekly limit", 0.0, 100000.0, None)
            total = c.checkbox("One total per day (like screen time)")
            if st.form_submit_button("Add tracker"):
                try:
                    cd.add_tracker(name, unit, daily, weekly, goal, "total" if total else "add")
                    st.rerun()
                except cd.CutError as e:
                    st.error(str(e))


def render_home():
    st.markdown("**Cut down**")
    today = store.local_today()
    bits = []
    for t in cd.trackers():
        s = cd.status(t, today)
        if t["goal"] == "quit":
            bits.append(f"{t['name']}: {s['days_free']} days free")
        else:
            lim = f"/{t['daily_limit']:g}" if t["daily_limit"] is not None else ""
            bits.append(f"{t['name']}: {s['today']:g}{lim} {t['unit']}" + (" ⚠" if s["over_today"] else ""))
    st.caption(" · ".join(bits) or "No trackers.")
