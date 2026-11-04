"""The Money page (this month vs budgets, transactions, budgets, savings goals, subscriptions,
bank CSV import) and its Home widget. The data is in venato/blocks/money.py."""

import pandas as pd
import streamlit as st

from venato import store
from venato import undo
from venato.blocks import money as mn


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


def _overview(day):
    s = mn.month_summary(day)
    a, b, c, d = st.columns(4)
    a.metric("Spent", mn.fmt(s["spent"]))
    b.metric("Income", mn.fmt(s["income"]))
    c.metric("Net", mn.fmt(s["net"]))
    if s["budget"]:
        d.metric("Budget left", mn.fmt(s["budget"] - sum(x["spent"] for x in s["categories"] if x["budget"])))
    for x in sorted(s["categories"], key=lambda x: -x["spent"]):
        if x["budget"]:
            over = x["spent"] > x["budget"]
            st.progress(min(1.0, x["spent"] / x["budget"]),
                        text=f"{x['name']}: {mn.fmt(x['spent'])} of {mn.fmt(x['budget'])}" + (" · **over**" if over else ""))
        else:
            st.caption(f"{x['name']}: {mn.fmt(x['spent'])}")
    if not s["categories"]:
        st.caption("Nothing logged this month yet.")


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
    for g in mn.savings():
        s = mn.goal_status(g)
        with st.container(border=True):
            x, y = st.columns([3, 2])
            x.markdown(f"**{g['name']}**" + (f" · by {store._as_date(g['deadline']):%-d %b %Y}" if g["deadline"] else ""))
            x.progress(s["pct"] / 100, text=f"{mn.fmt(g['saved'])} of {mn.fmt(g['target'])} ({s['pct']:.0f}%)"
                       + (f" · {mn.fmt(s['per_month'])}/month to make it" if s.get("per_month") else ""))
            with y.form(f"mn_g_{g['id']}", clear_on_submit=True, border=False):
                a, b = st.columns([2, 1], vertical_alignment="bottom")
                amt = a.number_input("Add (negative takes out)", -1_000_000.0, 1_000_000.0, None, 10.0)
                if b.form_submit_button("Save") and amt:
                    mn.contribute(g["id"], amt)
                    st.rerun()
            if y.button("Delete", key=f"mn_gd_{g['id']}", icon=":material/delete:"):
                undo.checkpoint(f"Deleted the savings goal {g['name']}")
                mn.delete_goal(g["id"])
                st.rerun()
    with st.form("mn_goal", clear_on_submit=True, border=False):
        a, b, c, d = st.columns([3, 2, 2, 2], vertical_alignment="bottom")
        name = a.text_input("New savings goal", placeholder="e.g. Interrailing")
        target = b.number_input(f"Target ({mn.currency()})", 0.0, 10_000_000.0, None, 50.0)
        saved = c.number_input("Saved so far", 0.0, 10_000_000.0, 0.0, 50.0)
        deadline = d.date_input("By", None)
        if st.form_submit_button("Add goal"):
            try:
                mn.add_goal(name, target, deadline, saved)
                st.rerun()
            except mn.MoneyError as e:
                st.error(str(e))


def _subscriptions():
    subs = mn.subscriptions()
    active = [s for s in subs if s["active"]]
    if active:
        st.metric("Subscriptions a month", mn.fmt(sum(mn.monthly_cost(s) for s in active)),
                  help=f"{mn.fmt(12 * sum(mn.monthly_cost(s) for s in active))} a year")
    for s in subs:
        with st.container(border=True):
            a, b, c, d = st.columns([3, 2, 2, 1], vertical_alignment="center")
            a.markdown(f"**{s['name']}** · {mn.fmt(s['amount'])} {s['period']}")
            b.caption(f"Next: {store._as_date(s['next_date']):%-d %b %Y}")
            on = c.toggle("Active", bool(s["active"]), key=f"mn_sa_{s['id']}")
            if on != bool(s["active"]):
                mn.update_subscription(s["id"], active=int(on))
                st.rerun()
            if d.button("", icon=":material/delete:", key=f"mn_sd_{s['id']}", help="Delete"):
                undo.checkpoint(f"Deleted the subscription {s['name']}")
                mn.delete_subscription(s["id"])
                st.rerun()
    with st.form("mn_sub", clear_on_submit=True, border=False):
        a, b, c, d = st.columns([3, 2, 2, 2], vertical_alignment="bottom")
        name = a.text_input("New subscription", placeholder="e.g. Spotify")
        amount = b.number_input(f"Amount ({mn.currency()})", 0.0, 100_000.0, None, 1.0)
        period = c.selectbox("Every", list(mn.PERIODS), index=1)
        nxt = d.date_input("Next payment", store.local_today())
        log = st.checkbox("Log each payment as spending", True)
        if st.form_submit_button("Add subscription"):
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
    tabs = st.tabs(["This month", "Transactions", "Budgets", "Savings", "Subscriptions", "Import"])
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
