"""
Money: spending and income by category with monthly budgets, savings goals, subscriptions
(their monthly cost, the next renewals, and optionally logging each renewal as spending),
and importing a bank's CSV export. Amounts are positive; whether it's money in or out is
its kind. One currency (Settings), shown with its symbol.
"""

import csv
import hashlib
import io
import re
import uuid
from datetime import date, datetime, timedelta

from venato import store
from venato.blocks import Block

SPEND = ["Groceries", "Eating out", "Transport", "Rent & bills", "Shopping", "Fun", "Health", "Subscriptions",
         "Gifts", "Other"]
INCOME = ["Pay", "Student loan / grant", "Gifts received", "Other income"]
GUESS = [   # (category, words in the note)
    ("Groceries", "groceries grocery tesco sainsbury aldi lidl asda waitrose morrisons supermarket food shop"),
    ("Eating out", "lunch dinner breakfast coffee cafe restaurant takeaway pizza burger nandos mcdonalds pub drinks"),
    ("Transport", "uber bus train tube taxi fuel petrol parking railcard oyster flight"),
    ("Rent & bills", "rent bill electricity gas water internet wifi phone council tax"),
    ("Shopping", "clothes shoes amazon shopping"),
    ("Fun", "cinema concert gig tickets game games bowling club"),
    ("Health", "pharmacy gym physio dentist medicine"),
    ("Subscriptions", "netflix spotify subscription prime disney"),
    ("Gifts", "gift present birthday"),
]
PERIODS = {"weekly": 7, "monthly": None, "yearly": None}

SCHEMA = """
CREATE TABLE IF NOT EXISTS mn_categories (
    id     TEXT PRIMARY KEY,
    name   TEXT NOT NULL UNIQUE COLLATE NOCASE,
    kind   TEXT NOT NULL,                  -- spend / income
    budget REAL,                           -- a month
    ord    INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS mn_transactions (
    id          TEXT PRIMARY KEY,
    date        TEXT NOT NULL,
    amount      REAL NOT NULL,             -- always positive
    kind        TEXT NOT NULL,             -- spend / income
    category_id TEXT REFERENCES mn_categories(id),
    note        TEXT,
    source      TEXT NOT NULL DEFAULT 'manual',   -- manual / subscription / import
    source_id   TEXT,                      -- e.g. a hash of the imported row, so imports don't repeat
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mn_savings (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE COLLATE NOCASE,
    target     REAL NOT NULL,
    saved      REAL NOT NULL DEFAULT 0,
    deadline   TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mn_subscriptions (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    amount      REAL NOT NULL,
    period      TEXT NOT NULL,             -- weekly / monthly / yearly
    next_date   TEXT NOT NULL,
    category_id TEXT REFERENCES mn_categories(id),
    active      INTEGER NOT NULL DEFAULT 1,
    auto_log    INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS mn_tx_date ON mn_transactions(date);
"""


class MoneyError(ValueError):
    pass


def _id():
    return uuid.uuid4().hex


def _amount(v):
    try:
        v = round(float(str(v).replace(",", "").replace("£", "").replace("$", "").replace("€", "").strip()), 2)
    except ValueError:
        raise MoneyError(f"'{v}' isn't an amount.")
    if not 0 < v < 10_000_000:
        raise MoneyError("The amount must be more than 0.")
    return v


# --- Settings ---

def currency():
    return (store.load_settings().get("money") or {}).get("currency", "£")


def set_currency(symbol):
    store.save_settings(money={**(store.load_settings().get("money") or {}), "currency": str(symbol).strip()[:4] or "£"})


def fmt(v):
    sign = "-" if v < 0 else ""
    return f"{sign}{currency()}{abs(v):,.2f}"


# --- Categories ---

C_COLS = ("id", "name", "kind", "budget", "ord")


def _seed(conn):
    if conn.execute("SELECT COUNT(*) FROM mn_categories").fetchone()[0]:
        return
    rows = [(_id(), n, "spend", None, i) for i, n in enumerate(SPEND)] + \
           [(_id(), n, "income", None, 100 + i) for i, n in enumerate(INCOME)]
    conn.executemany("INSERT INTO mn_categories VALUES (?, ?, ?, ?, ?)", rows)


def categories(kind=None):
    with store.db() as conn:
        _seed(conn)
        rows = conn.execute(f"SELECT {', '.join(C_COLS)} FROM mn_categories" + (" WHERE kind = ?" if kind else "")
                            + " ORDER BY ord, name", (kind,) if kind else ()).fetchall()
    return [dict(zip(C_COLS, r)) for r in rows]


def find_category(name, kind=None):
    want = str(name or "").strip().lower()
    pool = categories(kind)
    hit = [c for c in pool if c["name"].lower() == want or c["id"] == name]
    if hit:
        return hit[0]
    part = [c for c in pool if want and (c["name"].lower().startswith(want) or want in c["name"].lower())]
    return part[0] if len(part) == 1 else None


def guess_category(note, kind="spend"):
    """A category from words in the note ('lunch at Leon' -> Eating out), else Other / Other income."""
    words = set(re.findall(r"[a-z]+", str(note or "").lower()))
    if kind == "spend":
        for name, keys in GUESS:
            if words & set(keys.split()):
                return find_category(name, "spend")
        return find_category("Other", "spend")
    if words & {"pay", "paid", "salary", "wages", "payday"}:
        return find_category("Pay", "income")
    if words & {"loan", "grant", "bursary", "sfe"}:
        return find_category("Student loan / grant", "income")
    return find_category("Other income", "income")


def add_category(name, kind="spend", budget=None):
    name = str(name or "").strip()
    if not name or kind not in ("spend", "income"):
        raise MoneyError("A category needs a name and to be spend or income.")
    if find_category(name) and find_category(name)["name"].lower() == name.lower():
        raise MoneyError(f"There's already a category called {name}.")
    cid = _id()
    with store.db() as conn:
        conn.execute("INSERT INTO mn_categories VALUES (?, ?, ?, ?, ?)", (cid, name, kind, budget, 50))
    return cid


def set_budget(cid, budget):
    if budget not in (None, "") and float(budget) < 0:
        raise MoneyError("A budget can't be negative.")
    with store.db() as conn:
        conn.execute("UPDATE mn_categories SET budget = ? WHERE id = ?",
                     (None if budget in (None, "", 0) else float(budget), cid))


# --- Transactions ---

T_COLS = ("id", "date", "amount", "kind", "category_id", "note", "source", "source_id")


def add(amount, kind="spend", category=None, note=None, day=None, source="manual", source_id=None):
    if kind not in ("spend", "income"):
        raise MoneyError("kind is spend or income.")
    amount = _amount(amount)
    cat = (find_category(category, kind) if category else None) or guess_category(note, kind)
    day = store._as_date(day) if day else store.local_today()
    if source_id:
        with store.db() as conn:
            if conn.execute("SELECT 1 FROM mn_transactions WHERE source = ? AND source_id = ?",
                            (source, source_id)).fetchone():
                return None                    # already imported
    tid = _id()
    with store.db() as conn:
        conn.execute(f"INSERT INTO mn_transactions ({', '.join(T_COLS)}, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (tid, day.isoformat(), amount, kind, cat["id"] if cat else None,
                      (str(note).strip() or None) if note else None, source, source_id, store.stamp()))
    return tid


def transactions(first, last):
    with store.db() as conn:
        rows = conn.execute(f"SELECT {', '.join('t.' + c for c in T_COLS)}, c.name FROM mn_transactions t "
                            "LEFT JOIN mn_categories c ON c.id = t.category_id WHERE t.date BETWEEN ? AND ? "
                            "ORDER BY t.date DESC, t.created_at DESC", (str(first), str(last))).fetchall()
    return [dict(zip(T_COLS + ("category",), r)) for r in rows]


def update(tid, **fields):
    f = {k: v for k, v in fields.items() if k in ("date", "amount", "kind", "category_id", "note")}
    if "amount" in f:
        f["amount"] = _amount(f["amount"])
    if f:
        with store.db() as conn:
            conn.execute(f"UPDATE mn_transactions SET {', '.join(f'{k} = ?' for k in f)} WHERE id = ?", (*f.values(), tid))


def delete(tid):
    with store.db() as conn:
        conn.execute("DELETE FROM mn_transactions WHERE id = ?", (tid,))


def month_bounds(day=None):
    day = store._as_date(day) if day else store.local_today()
    first = day.replace(day=1)
    nxt = (first + timedelta(days=32)).replace(day=1)
    return first, nxt - timedelta(days=1)


def month_summary(day=None):
    """Income, spending, net, and per spending category: spent vs budget, for the month."""
    first, last = month_bounds(day)
    rows = transactions(first, last)
    spent = sum(r["amount"] for r in rows if r["kind"] == "spend")
    income = sum(r["amount"] for r in rows if r["kind"] == "income")
    cats = []
    for c in categories("spend"):
        s = sum(r["amount"] for r in rows if r["kind"] == "spend" and r["category_id"] == c["id"])
        if s or c["budget"]:
            cats.append({**c, "spent": s, "left": None if c["budget"] is None else c["budget"] - s})
    budget = sum(c["budget"] or 0 for c in categories("spend"))
    return {"first": first, "last": last, "spent": spent, "income": income, "net": income - spent,
            "categories": cats, "budget": budget or None}


# --- Savings goals ---

S_COLS = ("id", "name", "target", "saved", "deadline")


def savings():
    with store.db() as conn:
        rows = conn.execute(f"SELECT {', '.join(S_COLS)} FROM mn_savings ORDER BY deadline IS NULL, deadline, name").fetchall()
    return [dict(zip(S_COLS, r)) for r in rows]


def add_goal(name, target, deadline=None, saved=0):
    name = str(name or "").strip()
    if not name:
        raise MoneyError("The goal needs a name.")
    gid = _id()
    with store.db() as conn:
        if conn.execute("SELECT 1 FROM mn_savings WHERE name = ? COLLATE NOCASE", (name,)).fetchone():
            raise MoneyError(f"There's already a goal called {name}.")
        conn.execute(f"INSERT INTO mn_savings ({', '.join(S_COLS)}, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                     (gid, name, _amount(target), float(saved or 0), str(store._as_date(deadline)) if deadline else None,
                      store.stamp()))
    return gid


def find_goal(name):
    want = str(name or "").strip().lower()
    pool = savings()
    hit = [g for g in pool if g["name"].lower() == want] or [g for g in pool if want and want in g["name"].lower()]
    return hit[0] if len(hit) == 1 or (hit and hit[0]["name"].lower() == want) else None


def contribute(gid, amount):
    """Add to (or, negative, take from) a savings goal."""
    amount = float(amount)
    with store.db() as conn:
        conn.execute("UPDATE mn_savings SET saved = MAX(0, saved + ?) WHERE id = ?", (amount, gid))


def delete_goal(gid):
    with store.db() as conn:
        conn.execute("DELETE FROM mn_savings WHERE id = ?", (gid,))


def goal_status(g, today=None):
    today = today or store.local_today()
    left = max(0.0, g["target"] - g["saved"])
    out = {"left": left, "pct": min(100.0, 100 * g["saved"] / g["target"]) if g["target"] else 0}
    if g["deadline"] and left:
        months = max(1, round((store._as_date(g["deadline"]) - today).days / 30.44))
        out["per_month"] = left / months
    return out


# --- Subscriptions ---

SUB_COLS = ("id", "name", "amount", "period", "next_date", "category_id", "active", "auto_log")


def _advance(d, period):
    d = store._as_date(d)
    if period == "weekly":
        return d + timedelta(days=7)
    months = 12 if period == "yearly" else 1
    m = d.month - 1 + months
    y, m = d.year + m // 12, m % 12 + 1
    for day in (d.day, 30, 29, 28):          # 31 Jan -> 28/29 Feb
        try:
            return date(y, m, day)
        except ValueError:
            continue


def subscriptions(active_only=False):
    with store.db() as conn:
        rows = conn.execute(f"SELECT {', '.join(SUB_COLS)} FROM mn_subscriptions"
                            + (" WHERE active = 1" if active_only else "") + " ORDER BY next_date").fetchall()
    return [dict(zip(SUB_COLS, r)) for r in rows]


def add_subscription(name, amount, period="monthly", next_date=None, category=None, auto_log=True):
    name = str(name or "").strip()
    if not name or period not in PERIODS:
        raise MoneyError("A subscription needs a name and a period: weekly, monthly or yearly.")
    cat = find_category(category or "Subscriptions", "spend")
    sid = _id()
    with store.db() as conn:
        conn.execute(f"INSERT INTO mn_subscriptions ({', '.join(SUB_COLS)}, created_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)",
                     (sid, name, _amount(amount), period, str(store._as_date(next_date or store.local_today())),
                      cat["id"] if cat else None, int(bool(auto_log)), store.stamp()))
    return sid


def update_subscription(sid, **fields):
    f = {k: v for k, v in fields.items() if k in SUB_COLS[1:]}
    if "amount" in f:
        f["amount"] = _amount(f["amount"])
    if f:
        with store.db() as conn:
            conn.execute(f"UPDATE mn_subscriptions SET {', '.join(f'{k} = ?' for k in f)} WHERE id = ?", (*f.values(), sid))


def delete_subscription(sid):
    with store.db() as conn:
        conn.execute("DELETE FROM mn_subscriptions WHERE id = ?", (sid,))


def monthly_cost(s):
    return s["amount"] * {"weekly": 52 / 12, "monthly": 1, "yearly": 1 / 12}[s["period"]]


def log_renewals(today=None):
    """Log each renewal that has come round (for subscriptions set to), and move it on. Returns how many."""
    today = today or store.local_today()
    oldest = today - timedelta(days=366)       # a start date years back doesn't log years of payments
    n = 0
    for s in subscriptions(active_only=True):
        nxt = store._as_date(s["next_date"])
        while nxt <= today:
            if s["auto_log"] and nxt >= oldest:
                if add(s["amount"], "spend", s["category_id"], f"{s['name']} ({s['period']})", nxt, "subscription",
                       f"{s['id']}:{nxt.isoformat()}"):
                    n += 1
            nxt = _advance(nxt, s["period"])
        if nxt.isoformat() != s["next_date"]:
            update_subscription(s["id"], next_date=nxt.isoformat())
    return n


# --- Bank CSV import ---

def read_csv(raw):
    """(columns, rows) from a CSV file's bytes / text (comma, semicolon or tab separated)."""
    text = raw.decode("utf-8-sig", errors="replace") if isinstance(raw, bytes) else raw
    if len(text) > 20_000_000:
        raise MoneyError("That file is too big (over 20 MB).")
    try:
        dialect = csv.Sniffer().sniff(text[:5000], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.DictReader(io.StringIO(text), dialect=dialect))
    if not rows:
        raise MoneyError("No rows found in that file.")
    return list(rows[0].keys()), rows


def guess_columns(columns):
    """Which column is the date, the description, the amount (or money out / money in)."""
    low = {c: (c or "").strip().lower() for c in columns}
    def pick(*words):
        return next((c for c, l in low.items() if any(w in l for w in words)), None)
    return {"date": pick("date", "posted", "time"),
            "description": pick("description", "details", "narrative", "payee", "merchant", "reference", "name", "memo"),
            "amount": pick("amount", "value", "total"),
            "out": pick("paid out", "money out", "debit", "withdrawal", "out"),
            "in": pick("paid in", "money in", "credit", "deposit", "in")}


def _parse_date(text):
    text = str(text or "").strip()
    for f in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%m/%d/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(text[:10] if f == "%Y-%m-%d" else text, f).date()
        except ValueError:
            continue
    raise MoneyError(f"Couldn't read the date '{text[:30]}'.")


def _money(text):
    t = re.sub(r"[^\d.,\-()]", "", str(text or ""))
    if not t:
        return None
    neg = t.startswith("-") or (t.startswith("(") and t.endswith(")"))
    t = t.strip("-()")
    if "," in t and ("." not in t and len(t.split(",")[-1]) == 2 or "." in t and t.rfind(",") > t.rfind(".")):
        t = t.replace(".", "").replace(",", ".")   # 12,50 / 1.234,56 (European decimals)
    t = t.replace(",", "")
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def import_rows(rows, mapping, dry_run=False):
    """Turn CSV rows into transactions: a signed 'amount' column (negative = spending), or separate
    'out' / 'in' columns. Returns (preview rows, problems); without dry_run they're also saved
    (repeat imports of the same rows are skipped)."""
    out, problems, seen = [], [], {}
    for i, row in enumerate(rows, 1):
        try:
            day = _parse_date(row.get(mapping["date"]))
            note = (row.get(mapping.get("description")) or "").strip()[:200] if mapping.get("description") else ""
            if mapping.get("amount"):
                v = _money(row.get(mapping["amount"]))
                if v is None or v == 0:
                    continue
                kind, amount = ("spend", -v) if v < 0 else ("income", v)
            else:
                o = _money(row.get(mapping.get("out"))) if mapping.get("out") else None
                n = _money(row.get(mapping.get("in"))) if mapping.get("in") else None
                if o:
                    kind, amount = "spend", abs(o)
                elif n:
                    kind, amount = "income", abs(n)
                else:
                    continue
            # The same purchase twice in a day is two rows; counting repeats (not the row number) keeps
            # the key the same when a later export overlaps this one.
            base = f"{day}|{amount:.2f}|{kind}|{note.lower()}"
            seen[base] = seen.get(base, 0) + 1
            key = hashlib.sha256(f"{base}|{seen[base]}".encode()).hexdigest()[:24]
            cat = guess_category(note, kind)
            out.append({"date": day.isoformat(), "kind": kind, "amount": amount, "note": note,
                        "category": cat["name"] if cat else ""})
            if not dry_run:
                add(amount, kind, cat["id"] if cat else None, note, day, "import", key)
        except MoneyError as e:
            problems.append(f"Row {i}: {e}")
    return out, problems


# --- The assistant ---

def tool_add(amount, kind="spend", category=None, note=None, date=None):
    from venato import tools
    try:
        add(amount, kind, category, note, date)
    except MoneyError as e:
        raise tools.ToolError(str(e))
    s = month_summary(date)
    return tools.Result(f"Logged {fmt(_amount(amount))} {'spent' if kind == 'spend' else 'received'}"
                        + (f" ({note})" if note else "") + f". This month: spent {fmt(s['spent'])}, in {fmt(s['income'])}.",
                        changed=True)


def tool_summary(month=None):
    from venato import tools
    log_renewals()
    s = month_summary(month)
    lines = [f"{s['first']:%B %Y}: spent {fmt(s['spent'])}, income {fmt(s['income'])}, net {fmt(s['net'])}."]
    lines += [f"- {c['name']}: {fmt(c['spent'])}" + (f" of {fmt(c['budget'])} ({'over' if c['left'] < 0 else fmt(c['left']) + ' left'})"
                                                    if c["budget"] else "") for c in s["categories"]]
    goals = savings()
    if goals:
        lines.append("Savings: " + "; ".join(f"{g['name']} {fmt(g['saved'])}/{fmt(g['target'])}" for g in goals))
    subs = subscriptions(True)
    if subs:
        lines.append(f"Subscriptions: {fmt(sum(monthly_cost(x) for x in subs))}/month; next: "
                     + ", ".join(f"{x['name']} {x['next_date']}" for x in subs[:3]))
    return tools.Result("\n".join(lines))


def tool_budget(category, amount):
    from venato import tools
    c = find_category(category, "spend")
    if not c:
        raise tools.ToolError(f"No spending category '{category}'. There's: {', '.join(x['name'] for x in categories('spend'))}.")
    set_budget(c["id"], amount)
    return tools.Result(f"Budget for {c['name']}: {fmt(float(amount)) if amount else 'none'} a month.", changed=True)


def tool_goal(name, target=None, deadline=None, add_amount=None):
    from venato import tools
    g = find_goal(name)
    try:
        if not g:
            if target is None:
                raise tools.ToolError(f"No savings goal '{name}'. Give a target to make one.")
            add_goal(name, target, deadline)
            g = find_goal(name)
        if add_amount:
            contribute(g["id"], add_amount)
            g = find_goal(g["name"])
    except MoneyError as e:
        raise tools.ToolError(str(e))
    st = goal_status(g)
    return tools.Result(f"{g['name']}: {fmt(g['saved'])} of {fmt(g['target'])} ({st['pct']:.0f}%)"
                        + (f", {fmt(st['per_month'])}/month to make it" if st.get("per_month") else "") + ".", changed=True)


def tool_subscription(name, amount, period="monthly", next_date=None, category=None):
    from venato import tools
    try:
        add_subscription(name, amount, period, next_date, category)
    except MoneyError as e:
        raise tools.ToolError(str(e))
    return tools.Result(f"Added the subscription {name}: {fmt(_amount(amount))} {period}.", changed=True)


QUICK_SPEND = re.compile(r"(?:i\s+)?(?:spent|paid)\s+[£$€]?(\d+(?:[.,]\d{1,2})?)\s*(?:quid|pounds|dollars|euros)?"
                         r"(?:\s+(?:on|for|at)\s+(.+))?")
QUICK_INCOME = re.compile(r"(?:i\s+)?(?:got paid|earned|received|got)\s+[£$€]?(\d+(?:[.,]\d{1,2})?)(?:\s+(?:for|from)\s+(.+))?")


def _quick(text, day):
    """'spent £12 on lunch', 'paid 4.50 for coffee', 'got paid 1500', 'earned 200 from tutoring'."""
    m = QUICK_SPEND.fullmatch(text)
    if m:
        return tool_add(m.group(1).replace(",", "."), "spend", None, m.group(2), day.isoformat())
    m = QUICK_INCOME.fullmatch(text)
    if m and (text.startswith(("got paid", "earned", "received", "i got paid", "i earned")) or m.group(2)):
        note = m.group(2) or ("pay" if "paid" in text else None)
        return tool_add(m.group(1).replace(",", "."), "income", None, note, day.isoformat())
    return None


def _context():
    s = month_summary()
    over = [c["name"] for c in s["categories"] if c["budget"] and c["left"] < 0]
    text = f"This month: spent {fmt(s['spent'])}, income {fmt(s['income'])}" + (f" (over budget: {', '.join(over)})" if over else "") + "."
    soon = [x for x in subscriptions(True) if x["next_date"] <= (store.local_today() + timedelta(days=7)).isoformat()]
    if soon:
        text += " Renewing this week: " + ", ".join(f"{x['name']} {fmt(x['amount'])}" for x in soon) + "."
    return text + f" Currency {currency()}."


PROMPT = """- Money: spending and income by category, monthly budgets, savings goals and subscriptions (the Money page).
  "spent 12 on lunch" -> add_money(amount=12, kind="spend", note="lunch") (the category is guessed from the note,
  or pass one); "got paid 1500" -> kind="income". money_summary(month) shows the month by category vs budget;
  set_budget(category, amount); savings_goal(name, target, deadline, add_amount) makes or adds to a goal;
  add_subscription(name, amount, period, next_date)."""

TOOLS = [
    ("add_money", "Log money spent (kind spend) or received (kind income): amount, category (optional), note, date.",
     {"type": "object", "properties": {"amount": {"type": "number"}, "kind": {"type": "string", "enum": ["spend", "income"]},
                                       "category": {"type": "string"}, "note": {"type": "string"},
                                       "date": {"type": "string"}}, "required": ["amount"]}, tool_add),
    ("money_summary", "A month's spending by category vs budget, income, savings goals and subscriptions.",
     {"type": "object", "properties": {"month": {"type": "string", "description": "any date in the month"}},
      "required": []}, tool_summary),
    ("set_budget", "Set (or clear with 0) a spending category's monthly budget.",
     {"type": "object", "properties": {"category": {"type": "string"}, "amount": {"type": "number"}},
      "required": ["category", "amount"]}, tool_budget),
    ("savings_goal", "Make a savings goal (target, deadline) or add money to one (add_amount; negative takes out).",
     {"type": "object", "properties": {"name": {"type": "string"}, "target": {"type": "number"},
                                       "deadline": {"type": "string"}, "add_amount": {"type": "number"}},
      "required": ["name"]}, tool_goal),
    ("add_subscription", "Add a subscription: name, amount, period (weekly / monthly / yearly), next payment date.",
     {"type": "object", "properties": {"name": {"type": "string"}, "amount": {"type": "number"},
                                       "period": {"type": "string", "enum": list(PERIODS)},
                                       "next_date": {"type": "string"}, "category": {"type": "string"}},
      "required": ["name", "amount"]}, tool_subscription),
]


def _page():
    from venato.ui import money as ui
    ui.render_page()


def _home():
    from venato.ui import money as ui
    ui.render_home()


BLOCK = Block("money", "Money", ":material/account_balance_wallet:",
              "Spending and income by category, budgets, savings goals, subscriptions, and bank CSV imports.",
              group="Money", page=_page, home=_home, tools=TOOLS, prompt=PROMPT, context=_context,
              quick=[_quick], schema=SCHEMA, order=70)
