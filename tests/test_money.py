"""Money block: categories and guessing, month summary and budgets, savings, subscriptions, CSV import, quick, tools."""

import importlib
from datetime import date, timedelta

import pytest


@pytest.fixture
def mn(store):
    from venato import blocks, tools, quick
    importlib.reload(tools)
    importlib.reload(blocks)
    importlib.reload(quick)
    from venato.blocks import money as module
    module = importlib.reload(module)
    blocks.save(blocks.chosen_keys() + ["money"])
    return module


def test_add_guess_and_summary(mn, store):
    today = store.local_today()
    mn.add(12, note="lunch at Leon")
    mn.add("£3.50", note="coffee")
    mn.add(40, category="groceries", note="weekly shop")
    mn.add(1500, "income", note="got paid")
    mn.add(99, note="last month", day=today.replace(day=1) - timedelta(days=1))
    mn.set_budget(mn.find_category("Eating out")["id"], 10)
    s = mn.month_summary()
    assert s["spent"] == pytest.approx(55.5) and s["income"] == 1500 and s["net"] == pytest.approx(1444.5)
    eo = next(c for c in s["categories"] if c["name"] == "Eating out")
    assert eo["spent"] == pytest.approx(15.5) and eo["left"] == pytest.approx(-5.5)
    rows = mn.transactions(*mn.month_bounds())
    assert {r["category"] for r in rows} == {"Eating out", "Groceries", "Pay"}
    with pytest.raises(mn.MoneyError):
        mn.add(0)
    with pytest.raises(mn.MoneyError):
        mn.add("lots")
    mn.update(rows[0]["id"], amount=1)
    with pytest.raises(mn.MoneyError):
        mn.add_category("groceries")


def test_currency(mn):
    assert mn.fmt(-3.5) == "-£3.50"
    mn.set_currency("€")
    assert mn.fmt(1234) == "€1,234.00"


def test_savings(mn, store):
    gid = mn.add_goal("Interrailing", 600, store.local_today() + timedelta(days=183), 100)
    mn.contribute(gid, 50)
    g = mn.find_goal("interrail")
    st = mn.goal_status(g)
    assert g["saved"] == 150 and st["left"] == 450 and st["per_month"] == pytest.approx(75)
    mn.contribute(gid, -1000)
    assert mn.find_goal("Interrailing")["saved"] == 0
    with pytest.raises(mn.MoneyError):
        mn.add_goal("interrailing", 10)


def test_subscriptions_and_renewals(mn, store):
    today = store.local_today()
    assert mn._advance(date(2026, 1, 31), "monthly") == date(2026, 2, 28)
    assert mn._advance(date(2024, 2, 29), "yearly") == date(2025, 2, 28)
    sid = mn.add_subscription("Spotify", 11.99, "monthly", today - timedelta(days=40))
    mn.add_subscription("Gym", 5, "weekly", today + timedelta(days=3), auto_log=False)
    assert mn.log_renewals() == 2                  # two months came round
    assert mn.log_renewals() == 0                  # not twice
    s = next(x for x in mn.subscriptions() if x["id"] == sid)
    assert s["next_date"] > today.isoformat()
    total = sum(mn.monthly_cost(x) for x in mn.subscriptions(True))
    assert total == pytest.approx(11.99 + 5 * 52 / 12)
    with pytest.raises(mn.MoneyError):
        mn.add_subscription("x", 1, "daily")


def test_csv_import(mn):
    raw = ("Date,Description,Amount\n"
           "01/10/2026,TESCO STORES,-23.40\n"
           "02/10/2026,Salary ACME,1500.00\n"
           "03/10/2026,Refund,0\n"
           "nope,Bad row,-1\n").encode()
    cols, rows = mn.read_csv(raw)
    m = mn.guess_columns(cols)
    assert m["date"] == "Date" and m["amount"] == "Amount" and m["description"] == "Description"
    preview, problems = mn.import_rows(rows, m, dry_run=True)
    assert [(p["kind"], p["amount"], p["category"]) for p in preview] == [("spend", 23.4, "Groceries"),
                                                                          ("income", 1500.0, "Pay")]
    assert len(problems) == 1 and not mn.transactions("2026-10-01", "2026-10-31")
    mn.import_rows(rows, m)
    mn.import_rows(rows, m)                         # again: no doubles
    assert len(mn.transactions("2026-10-01", "2026-10-31")) == 2
    semi = "Posted;Details;Money out;Money in\n2026-09-05;Uber;12,50;\n2026-09-06;Loan;;2000\n"
    cols, rows = mn.read_csv(semi)
    m = mn.guess_columns(cols)
    assert m["out"] == "Money out" and m["in"] == "Money in"
    m["amount"] = None
    preview, _ = mn.import_rows(rows, m, dry_run=True)
    assert [(p["kind"], p["amount"], p["category"]) for p in preview] == [("spend", 12.5, "Transport"),
                                                                          ("income", 2000.0, "Student loan / grant")]


def test_quick_and_tools(mn):
    from venato import quick, assistant
    assert "£12.00 spent (lunch)" in quick.handle("spent £12 on lunch").reply
    assert "£4.50" in quick.handle("paid 4.50 for coffee").reply
    assert "received" in quick.handle("got paid 1500").reply
    assert quick.handle("got 68 in nothing really") is None
    s = mn.month_summary()
    assert s["spent"] == pytest.approx(16.5) and s["income"] == 1500
    assert "Budget for Eating out: £20.00" in mn.tool_budget("eating", 20).text
    assert "Holiday: £50.00 of £500.00" in mn.tool_goal("Holiday", 500, None, 50).text
    assert "Netflix" in mn.tool_subscription("Netflix", 5.99).text
    out = mn.tool_summary().text
    assert "Eating out: £16.50 of £20.00" in out and "Holiday" in out and "Netflix" in out
    names = {t[0] for t in assistant.tool_specs()}
    assert {"add_money", "money_summary", "set_budget", "savings_goal", "add_subscription"} <= names
    assert "spent" in mn._context()


def test_old_subscription_logs_at_most_a_year(mn, store):
    mn.add_subscription("Old", 1, "weekly", store.local_today() - timedelta(days=3650))
    assert 50 <= mn.log_renewals() <= 54


def test_import_overlapping_exports_and_european_amounts(mn):
    assert mn._money("1.234,56") == 1234.56 and mn._money("1,234.56") == 1234.56 and mn._money("(12.50)") == -12.5
    m = {"date": "Date", "description": "Description", "amount": "Amount"}
    first = [{"Date": "2026-10-01", "Description": "Coffee", "Amount": "-3"},
             {"Date": "2026-10-01", "Description": "Coffee", "Amount": "-3"},      # really twice
             {"Date": "2026-10-02", "Description": "Bus", "Amount": "-2"}]
    mn.import_rows(first, m)
    later = [{"Date": "2026-09-30", "Description": "Lunch", "Amount": "-8"}] + first + \
            [{"Date": "2026-10-03", "Description": "Tesco", "Amount": "-20"}]
    mn.import_rows(later, m)
    assert len(mn.transactions("2026-09-30", "2026-10-03")) == 5
