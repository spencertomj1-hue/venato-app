"""The Money page (this month vs budgets, transactions, budgets, savings goals, subscriptions,
bank CSV import) and its Home widget. The data is in venato/blocks/money.py."""

from datetime import timedelta

import altair as alt
import pandas as pd
import streamlit as st

from venato import store
from venato import undo
from venato.blocks import money as mn
from venato.ui import kit


TX_FIELD = {"Date": "date", "Amount": "amount", "Note": "note"}


def _apply_tx(key, rows, cats):
    state = st.session_state.get(key) or {}
    by_name = {c["name"]: c["id"] for c in cats}
    try:
        for i in state.get("deleted_rows", []):
            if int(i) < len(rows):
                mn.delete(rows[int(i)]["id"])
        for i, changes in state.get("edited_rows", {}).items():
            if int(i) >= len(rows):
                continue
            f = {TX_FIELD[c]: v for c, v in changes.items() if c in TX_FIELD}
            if "date" in f and f["date"]:
                f["date"] = str(store._as_date(f["date"]))
            if "Category" in changes and changes["Category"] in by_name:
                f["category_id"] = by_name[changes["Category"]]
            if "In/out" in changes:
                f["kind"] = "income" if changes["In/out"] == "In" else "spend"
            mn.update(rows[int(i)]["id"], **f)
    except (mn.MoneyError, ValueError) as e:
        st.toast(str(e), icon=":material/error:")


_colours = kit.colours
_good_bad = kit.good_bad


def _table(rows, money=(), progress=(), dates=None):
    kit.table(rows, money=money, fmt=mn.fmt, progress=progress, dates=dates)


def _delta(now, before):
    """'+£12.00 vs last month', or None when there's nothing last month to compare with."""
    if not before:
        return None
    d = now - before
    return f"{'+' if d >= 0 else '-'}{mn.fmt(abs(d))} vs last month"


def _kpis(s, prev):
    budgeted_spent = sum(x["spent"] for x in s["categories"] if x["budget"])
    a, b, c, d = st.columns(4)
    if s["budget"]:
        left = s["budget"] - budgeted_spent
        a.metric("Left to spend", mn.fmt(left), border=True,
                 delta=f"{100 * budgeted_spent / s['budget']:.0f}% of {mn.fmt(s['budget'])} used",
                 delta_color="normal" if left >= 0 else "inverse", delta_arrow="off",
                 help="Your monthly budgets minus what's been spent in budgeted categories")
    else:
        a.metric("Left to spend", "No budget", border=True, help="Set monthly budgets in the Budgets tab")
    b.metric("Spent", mn.fmt(s["spent"]), _delta(s["spent"], prev["spent"]), "inverse", border=True)
    c.metric("Income", mn.fmt(s["income"]), _delta(s["income"], prev["income"]), border=True)
    d.metric("Net", mn.fmt(s["net"]), _delta(s["net"], prev["net"]) if prev["spent"] or prev["income"] else None,
             border=True, help="Income minus spending")


def _where_it_went(s, colours):
    with st.container(border=True, height="stretch"):
        st.markdown("**Where it went**")
        cats = sorted([x for x in s["categories"] if x["spent"]], key=lambda x: -x["spent"])
        if not cats:
            st.caption("No spending this month yet.")
            return
        df = pd.DataFrame({"Category": [x["name"] for x in cats], "Spent": [x["spent"] for x in cats]})
        df["Share"] = df["Spent"] / df["Spent"].sum()
        scale = kit.colour_scale(df["Category"], colours)
        arcs = alt.Chart(df).mark_arc(innerRadius=62, outerRadius=96, stroke="rgba(0,0,0,0)").encode(
            theta=alt.Theta("Spent", type="quantitative", stack=True),
            color=alt.Color("Category", type="nominal", scale=scale, sort=None),
            order=alt.value(0),
            tooltip=["Category", alt.Tooltip("Spent", format=",.2f", title=f"Spent ({mn.currency()})"),
                     alt.Tooltip("Share", format=".0%")])
        middle = alt.Chart(pd.DataFrame({"t": [mn.fmt(s["spent"])]})).mark_text(fontSize=20, fontWeight="bold",
                                                                            dy=-6, color=kit.ink()).encode(text="t:N")
        sub = alt.Chart(pd.DataFrame({"t": ["spent"]})).mark_text(fontSize=12, dy=14, opacity=0.8, color=kit.ink()).encode(text="t:N")
        kit.show(kit.style(arcs + middle + sub, 320, legend=True, legend_columns=2), key="mn_dash_donut")


def _budget_vs_actual(s, colours):
    with st.container(border=True, height="stretch"):
        st.markdown("**Budget vs actual**")
        cats = [x for x in s["categories"] if x["budget"]]
        if not cats:
            st.caption("No budgets set yet. Add them in the Budgets tab.")
            return
        # As a share of each budget, so a big rent budget doesn't squash the small ones.
        cats = sorted(cats, key=lambda x: x["spent"] / x["budget"])
        names = [x["name"] for x in cats]
        used = [x["spent"] / x["budget"] for x in cats]
        _, bad = _good_bad()
        df = pd.DataFrame({"Category": names, "Used": [min(u, 1.25) for u in used], "Share": used,
                           "Detail": [f"{mn.fmt(x['spent'])} / {mn.fmt(x['budget'])}" for x in cats]})
        df["Colour"] = [bad if u > 1 else colours[n] for n, u in zip(names, used)]
        top = max(1.05, min(max(used), 1.25) + 0.05)
        x_enc = alt.X("Used", type="quantitative", scale=alt.Scale(domain=[0, top], nice=False),
                      axis=alt.Axis(format=".0%", title=None))
        y_enc = alt.Y("Category", type="nominal", sort=names[::-1], axis=alt.Axis(grid=False, title=None, labelLimit=160))
        track = alt.Chart(df).mark_bar(color=kit.TRACK, size=22).encode(
            x=alt.X("one:Q", scale=alt.Scale(domain=[0, top], nice=False), axis=alt.Axis(format=".0%", title=None)),
            y=y_enc).transform_calculate(one="1")
        bars = alt.Chart(df).mark_bar(size=12).encode(
            x=x_enc, y=y_enc, color=alt.Color("Colour", type="nominal", scale=None),
            tooltip=["Category", "Detail", alt.Tooltip("Share", format=".0%", title="Of budget")])
        goal = alt.Chart(pd.DataFrame({"x": [1]})).mark_rule(strokeDash=[3, 3], color="rgba(128,128,128,0.8)").encode(
            x=alt.X("x:Q", scale=alt.Scale(domain=[0, top], nice=False)))
        kit.show(kit.style(track + bars + goal, 320, legend=False), key="mn_dash_bva")
        over = [x["name"] for x in cats if x["spent"] > x["budget"]]
        if over:
            st.caption(f":red[Over budget on {', '.join(over)}]")


def _pace(s):
    with st.container(border=True, height="stretch"):
        st.markdown("**Spending through the month**")
        first, last = s["first"], s["last"]
        today = store.local_today()
        end = min(last, today) if first <= today else last
        days = [first + timedelta(days=i) for i in range((end - first).days + 1)]
        if not s["by_day"]:
            st.caption("No spending this month yet.")
            return
        total, running = 0, []
        for d in days:
            total += s["by_day"].get(d, 0)
            running.append(total)
        good, bad = _good_bad()
        over = bool(s["budget"]) and running[-1] > s["budget"] * len(days) / ((last - first).days + 1)
        colour = bad if over else good
        x_enc = alt.X("Day", type="temporal", scale=alt.Scale(domain=[pd.Timestamp(first).isoformat(),
                                                                       pd.Timestamp(last).isoformat()], nice=False),
                      axis=alt.Axis(format=kit.DAY_FORMAT, grid=False, labelOverlap=True, labelAngle=0, title=None))
        y_enc = alt.Y("Spent", type="quantitative", scale=alt.Scale(zero=True),
                      axis=alt.Axis(labelExpr=f"'{mn.currency()}' + format(datum.value, ',.0f')", title=None))
        df = pd.DataFrame({"Day": pd.to_datetime(days), "Spent": running})
        area = alt.Chart(df).mark_area(interpolate="step-after", color=colour, opacity=0.12).encode(x=x_enc, y=y_enc)
        line = alt.Chart(df).mark_line(interpolate="step-after", color=colour, strokeWidth=3).encode(
            x=x_enc, y=y_enc, tooltip=[alt.Tooltip("Day", format=kit.DAY_FORMAT), alt.Tooltip("Spent", format=",.2f")])
        layers = area + line
        if s["budget"]:
            n = (last - first).days + 1
            pace = pd.DataFrame({"Day": pd.to_datetime([first, last]), "Spent": [s["budget"] / n, s["budget"]]})
            layers = alt.Chart(pace).mark_line(color="rgba(128,128,128,0.8)", strokeDash=[4, 4]).encode(
                x=x_enc, y=y_enc, tooltip=alt.value("Even pace")) + layers
        kit.show(kit.style(layers, 280, legend=False), key="mn_dash_pace")
        if s["budget"]:
            st.caption("Ahead of an even pace for your budget." if over else "On track for your budget.")


def _budget_table(s):
    with st.container(border=True, height="stretch"):
        st.markdown("**Budgets**")
        cats = sorted([x for x in s["categories"] if x["budget"]], key=lambda x: -x["spent"] / x["budget"])
        if not cats:
            st.caption("No budgets set yet.")
            return
        _table([{"Category": x["name"], "Spent": x["spent"], "Left": x["left"],
                 "Used": min(1.0, x["spent"] / x["budget"])} for x in cats], money=("Spent", "Left"),
               progress=("Used",))


def _cash_flow(s, subs):
    with st.container(border=True, height="stretch"):
        st.markdown("**Cash flow**")
        rows = [{"": "Income", "Amount": s["income"]}, {"": "Spending", "Amount": -s["spent"]}]
        rows += [{"": f"    {x['name']}", "Amount": -x["spent"]}
                 for x in sorted(s["categories"], key=lambda x: -x["spent"]) if x["spent"]]
        rows.append({"": "Net", "Amount": s["net"]})
        _table(rows, money=("Amount",))
        if subs:
            st.caption(f"Subscriptions: {mn.fmt(sum(mn.monthly_cost(x) for x in subs))} a month")


def _income(s, colours):
    with st.container(border=True, height="stretch"):
        st.markdown("**Income**")
        if not s["income_categories"]:
            st.caption("No income logged this month.")
            return
        _table([{"Source": n, "Amount": v, "Share": v / s["income"]} for n, v in s["income_categories"]],
               money=("Amount",), progress=("Share",))
        if s["income"]:
            rate = s["net"] / s["income"]
            st.caption(f"You kept {rate:.0%} of what came in." if rate >= 0
                       else f"You spent {-rate:.0%} more than came in.")


def _goals_card():
    with st.container(border=True, height="stretch"):
        st.markdown("**Savings goals**")
        goals = mn.savings()
        if not goals:
            st.caption("No savings goals yet. Add one in the Savings tab.")
            return
        st.caption(f"{mn.fmt(sum(g['saved'] for g in goals))} saved of {mn.fmt(sum(g['target'] for g in goals))}")
        for g in goals:
            gs = mn.goal_status(g)
            extra = f" · {mn.fmt(gs['per_month'])}/month" if gs.get("per_month") else ""
            st.progress(gs["pct"] / 100, text=f"{g['name']}: {mn.fmt(g['saved'])} of {mn.fmt(g['target'])}{extra}")


def _subs_card(subs):
    with st.container(border=True, height="stretch"):
        st.markdown("**Coming up**")
        if not subs:
            st.caption("No active subscriptions.")
            return
        st.caption(f"{mn.fmt(sum(mn.monthly_cost(x) for x in subs))} a month · "
                   f"{mn.fmt(12 * sum(mn.monthly_cost(x) for x in subs))} a year")
        nxt = sorted(subs, key=lambda x: x["next_date"])[:6]
        _table([{"Subscription": x["name"], "Amount": x["amount"], "Next": store._as_date(x["next_date"])}
                for x in nxt], money=("Amount",), dates={"Next": "ddd D MMM"})


def _recent(s):
    with st.container(border=True):
        st.markdown("**Latest transactions**")
        rows = mn.transactions(s["first"], s["last"])[:8]
        if not rows:
            st.caption("Nothing logged this month yet.")
            return
        _table([{"Date": store._as_date(r["date"]), "Amount": r["amount"] if r["kind"] == "income" else -r["amount"],
                 "Category": r["category"] or "", "Note": r["note"] or ""} for r in rows],
               money=("Amount",), dates={"Date": "ddd D MMM"})


def _overview(day):
    s = mn.month_summary(day)
    prev = mn.month_summary(s["first"] - timedelta(days=1))
    subs = mn.subscriptions(active_only=True)
    colours = _colours([c["name"] for c in mn.categories("spend")])
    st.subheader(f"{s['first']:%B %Y}", divider="gray")
    _kpis(s, prev)
    a, b, c = st.columns(3)
    with a:
        _where_it_went(s, colours)
    with b:
        _budget_vs_actual(s, colours)
    with c:
        _pace(s)
    a, b, c = st.columns(3)
    with a:
        _cash_flow(s, subs)
    with b:
        _budget_table(s)
    with c:
        _income(s, colours)
    a, b = st.columns(2)
    with a:
        _goals_card()
    with b:
        _subs_card(subs)
    _recent(s)


def _add_form(cats):
    with st.form("mn_add", clear_on_submit=True, border=False):
        a, b, c, d, e = st.columns([1, 1, 2, 3, 2], vertical_alignment="bottom")
        kind = a.selectbox("In/out", ["Out", "In"])
        amount = b.number_input(f"Amount ({mn.currency()})", 0.0, 10_000_000.0, None, 0.5)
        cat = c.selectbox("Category", ["(guess)"] + [x["name"] for x in cats])
        note = d.text_input("Note", placeholder="e.g. lunch at Leon")
        day = e.date_input("Date", store.local_today())
        if st.form_submit_button("Add", icon=":material/add:"):
            try:
                k = "income" if kind == "In" else "spend"
                chosen = None if cat == "(guess)" else cat
                if chosen and mn.find_category(chosen, k) is None:
                    chosen = None                       # a spend category on income: guess instead
                mn.add(amount, k, chosen, note, day)
                st.rerun()
            except mn.MoneyError as e:
                st.error(str(e))


def _transactions(day):
    first, last = mn.month_bounds(day)
    cats = mn.categories()
    _add_form(cats)
    rows = mn.transactions(first, last)
    if not rows:
        st.caption("No transactions this month.")
        return
    df = pd.DataFrame([{"Date": store._as_date(r["date"]), "In/out": "In" if r["kind"] == "income" else "Out",
                        "Amount": r["amount"], "Category": r["category"] or "", "Note": r["note"] or "",
                        "From": r["source"]} for r in rows])
    key = f"mn_tx_{first}"
    st.data_editor(df, key=key, on_change=_apply_tx, args=(key, rows, cats), num_rows="delete", hide_index=True,
                   width="stretch", disabled=["From"],
                   column_config={"Date": st.column_config.DateColumn(),
                                  "In/out": st.column_config.SelectboxColumn(options=["Out", "In"], required=True),
                                  "Amount": st.column_config.NumberColumn(min_value=0.01, format="%.2f"),
                                  "Category": st.column_config.SelectboxColumn(options=[c["name"] for c in cats])})


def _budgets():
    st.caption("A monthly budget per spending category. Leave empty for none.")
    for c in mn.categories("spend"):
        x, y = st.columns([3, 2], vertical_alignment="center")
        x.markdown(c["name"])
        v = y.number_input(c["name"], 0.0, 1_000_000.0, c["budget"], 10.0, key=f"mn_b_{c['id']}",
                           label_visibility="collapsed")
        if v != c["budget"]:
            mn.set_budget(c["id"], v)
            st.rerun()
    with st.form("mn_cat", clear_on_submit=True, border=False):
        x, y, z = st.columns([3, 2, 1], vertical_alignment="bottom")
        name = x.text_input("New category")
        kind = y.selectbox("Kind", ["spend", "income"])
        if z.form_submit_button("Add"):
            try:
                mn.add_category(name, kind)
                st.rerun()
            except mn.MoneyError as e:
                st.error(str(e))


def _savings():
    goals = mn.savings()
    good, _ = kit.good_bad()
    cols = st.columns(3)
    for i, g in enumerate(goals):
        gs = mn.goal_status(g)
        colour = good if gs["pct"] >= 100 else kit.PALETTE[i % len(kit.PALETTE)]
        with cols[i % 3], st.container(border=True, height="stretch"):
            st.markdown(f"**{g['name']}**")
            st.caption(f"by {store.fmt_day(store._as_date(g['deadline']), '%-d %b %Y')}" if g["deadline"] else "No deadline")
            kit.rings([{"frac": gs["pct"] / 100, "colour": colour, "size": 120, "centre": f"{gs['pct']:.0f}%",
                        "centre_sub": "saved", "title": f"{mn.fmt(g['saved'])} of {mn.fmt(g['target'])}",
                        "sub": f"{mn.fmt(gs['per_month'])}/month to make it" if gs.get("per_month") else ""}])
            with st.form(f"mn_g_{g['id']}", clear_on_submit=True, border=False):
                a, b = st.columns([2, 1], vertical_alignment="bottom")
                amt = a.number_input("Add (negative takes out)", -1_000_000.0, 1_000_000.0, None, 10.0)
                if b.form_submit_button("Save", width="stretch") and amt:
                    mn.contribute(g["id"], amt)
                    st.rerun()
            with st.popover("Delete", icon=":material/delete:"):
                st.warning(f"Delete the savings goal {g['name']}?")
                if st.button("Delete", key=f"mn_gd_{g['id']}", type="primary"):
                    undo.checkpoint(f"Deleted the savings goal {g['name']}")
                    mn.delete_goal(g["id"])
                    st.rerun()
    if not goals:
        kit.empty("No savings goals yet.", ":material/savings:")
    with kit.card("New savings goal", stretch=False):
        with st.form("mn_goal", clear_on_submit=True, border=False):
            a, b, c, d = st.columns([3, 2, 2, 2], vertical_alignment="bottom")
            name = a.text_input("Name", placeholder="e.g. Interrailing")
            target = b.number_input(f"Target ({mn.currency()})", 0.0, 10_000_000.0, None, 50.0)
            saved = c.number_input("Saved so far", 0.0, 10_000_000.0, 0.0, 50.0)
            deadline = d.date_input("By", None)
            if st.form_submit_button("Add goal", type="primary", icon=":material/add:"):
                try:
                    mn.add_goal(name, target, deadline, saved)
                    st.rerun()
                except mn.MoneyError as e:
                    st.error(str(e))


def _subscriptions():
    subs = mn.subscriptions()
    active = [s for s in subs if s["active"]]
    if active:
        month = sum(mn.monthly_cost(s) for s in active)
        kit.stats([{"label": "Subscriptions a month", "value": mn.fmt(month)},
                   {"label": "A year", "value": mn.fmt(12 * month)},
                   {"label": "Active", "value": f"{len(active)} of {len(subs)}"}])
    cols = st.columns(3)
    today = store.local_today()
    for i, s in enumerate(subs):
        nxt = store._as_date(s["next_date"])
        with cols[i % 3], st.container(border=True, height="stretch"):
            kit.html(f"<div style='display:flex;gap:12px;align-items:center'>{kit.date_badge(nxt)}<div>"
                     f"<b>{s['name']}</b><br><span style='opacity:.7;font-size:.85rem'>{mn.fmt(s['amount'])} "
                     f"{s['period']} · {'today' if nxt == today else f'in {(nxt - today).days} days' if nxt > today else 'due'}"
                     f"</span></div></div>")
            a, b = st.columns([3, 1], vertical_alignment="center")
            on = a.toggle("Active", bool(s["active"]), key=f"mn_sa_{s['id']}")
            if on != bool(s["active"]):
                mn.update_subscription(s["id"], active=int(on))
                st.rerun()
            with b.popover("", icon=":material/delete:", help="Delete"):
                st.warning(f"Delete {s['name']}?")
                if st.button("Delete", key=f"mn_sd_{s['id']}", type="primary"):
                    undo.checkpoint(f"Deleted the subscription {s['name']}")
                    mn.delete_subscription(s["id"])
                    st.rerun()
    if not subs:
        kit.empty("No subscriptions yet.", ":material/autorenew:")
    with kit.card("New subscription", stretch=False):
        with st.form("mn_sub", clear_on_submit=True, border=False):
            a, b, c, d = st.columns([3, 2, 2, 2], vertical_alignment="bottom")
            name = a.text_input("Name", placeholder="e.g. Spotify")
            amount = b.number_input(f"Amount ({mn.currency()})", 0.0, 100_000.0, None, 1.0)
            period = c.selectbox("Every", list(mn.PERIODS), index=1)
            nxt = d.date_input("Next payment", store.local_today())
            log = st.checkbox("Log each payment as spending", True)
            if st.form_submit_button("Add subscription", type="primary", icon=":material/add:"):
                try:
                    mn.add_subscription(name, amount, period, nxt, None, log)
                    mn.log_renewals()
                    st.rerun()
                except mn.MoneyError as e:
                    st.error(str(e))


def _import():
    st.caption("Import a CSV export from your bank. Nothing is saved until you press Import; importing the same "
               "file twice won't double up.")
    f = st.file_uploader("Bank CSV", type=["csv", "txt"], key="mn_csv")
    if not f:
        return
    try:
        cols, rows = mn.read_csv(f.getvalue())
    except mn.MoneyError as e:
        st.error(str(e))
        return
    g = mn.guess_columns(cols)
    opts = [""] + cols
    a, b = st.columns(2)
    date_col = a.selectbox("Date column", opts, opts.index(g["date"]) if g["date"] in opts else 0)
    desc_col = b.selectbox("Description column", opts, opts.index(g["description"]) if g["description"] in opts else 0)
    signed = st.radio("Amounts are", ["One column (negative = spent)", "Separate money out / money in columns"],
                      index=0 if g["amount"] else 1, horizontal=True)
    m = {"date": date_col, "description": desc_col or None}
    if signed.startswith("One"):
        m["amount"] = st.selectbox("Amount column", opts, opts.index(g["amount"]) if g["amount"] in opts else 0)
    else:
        a, b = st.columns(2)
        m["out"] = a.selectbox("Money out column", opts, opts.index(g["out"]) if g["out"] in opts else 0) or None
        m["in"] = b.selectbox("Money in column", opts, opts.index(g["in"]) if g["in"] in opts else 0) or None
    if not date_col or not (m.get("amount") or m.get("out") or m.get("in")):
        st.info("Pick the date and amount columns.")
        return
    preview, problems = mn.import_rows(rows, m, dry_run=True)
    st.caption(f"{len(preview)} transactions found" + (f", {len(problems)} rows skipped" if problems else ""))
    if preview:
        st.dataframe(pd.DataFrame(preview[:50]), hide_index=True, width="stretch")
    if problems:
        with st.expander("Skipped rows"):
            st.write("\n".join(problems[:50]))
    if preview and st.button(f"Import {len(preview)}", type="primary", key="mn_do_import"):
        undo.checkpoint("Imported a bank CSV")
        mn.import_rows(rows, m)
        st.toast("Imported.", icon=":material/check:")
        st.rerun()


def render_page():
    st.title("Money")
    mn.log_renewals()
    x, y, _ = st.columns([2, 1, 3])
    day = x.date_input("Month", store.local_today(), key="mn_month", format="DD/MM/YYYY",
                       help="Any day in the month to show")
    cur = y.text_input("Currency symbol", mn.currency(), max_chars=4, key="mn_cur")
    if cur.strip() and cur.strip() != mn.currency():
        mn.set_currency(cur)
        st.rerun()
    tabs = st.tabs(["Dashboard", "Transactions", "Budgets", "Savings", "Subscriptions", "Import"])
    with tabs[0]:
        _overview(day)
    with tabs[1]:
        _transactions(day)
    with tabs[2]:
        _budgets()
    with tabs[3]:
        _savings()
    with tabs[4]:
        _subscriptions()
    with tabs[5]:
        _import()


def render_home():
    st.markdown("**Money**")
    mn.log_renewals()
    s = mn.month_summary()
    text = f"Spent {mn.fmt(s['spent'])} this month"
    if s["budget"]:
        text += f" of {mn.fmt(s['budget'])} budgeted"
    over = [c["name"] for c in s["categories"] if c["budget"] and c["left"] < 0]
    if over:
        text += f" · over on {', '.join(over)}"
    goals = mn.savings()
    if goals:
        g = goals[0]
        text += f" · {g['name']} {mn.goal_status(g)['pct']:.0f}%"
    st.caption(text)
