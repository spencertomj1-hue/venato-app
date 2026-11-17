"""The Food page: the day's diary, the week's meal plan, trends, your foods and targets, and (with
the Recipes block) recipes and the shopping list as tabs. Also the Food Home widget.
The data is in venato/blocks/food.py and venato/blocks/recipes.py."""

from datetime import timedelta
from html import escape

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from venato import blocks
from venato import store
from venato import undo
from venato.blocks import food
from venato.ui import kit

LABELS = {"kcal": "Calories", "protein": "Protein", "carbs": "Carbs", "fat": "Fat", "fibre": "Fibre"}
UNIT = {"kcal": "kcal", "protein": "g", "carbs": "g", "fat": "g", "fibre": "g"}
# Macro colours, the same on the rings and the charts.
MACRO = {"protein": "#4E79A7", "carbs": "#F28E2B", "fat": "#B07AA1", "fibre": "#59A14F"}
MEAL_ICON = {"breakfast": ":material/egg_alt:", "lunch": ":material/lunch_dining:",
             "dinner": ":material/dinner_dining:", "snacks": ":material/cookie:"}


def _n(v):
    return f"{v:,.0f}"


# --- Today ---

def _day_picker():
    today = store.local_today()
    if "fd_day" not in st.session_state:
        st.session_state["fd_day"] = today

    def shift(n):
        st.session_state["fd_day"] = st.session_state["fd_day"] + timedelta(days=n)

    a, b, c, d, _ = st.columns([0.5, 2, 0.5, 1, 4], vertical_alignment="bottom")
    a.button("", icon=":material/chevron_left:", key="fd_prev", on_click=shift, args=(-1,), help="The day before",
             width="stretch")
    b.date_input("Day", key="fd_day", format="DD/MM/YYYY", label_visibility="collapsed")
    c.button("", icon=":material/chevron_right:", key="fd_next", on_click=shift, args=(1,), help="The day after",
             width="stretch")
    if st.session_state["fd_day"] != today:
        d.button("Today", key="fd_today", on_click=lambda: st.session_state.update(fd_day=today), type="tertiary")
    return st.session_state["fd_day"]


def _summary(day):
    t, tg = food.totals(day), food.targets()
    good, bad = kit.good_bad()
    kcal, target = t.get("kcal") or 0, tg.get("kcal")
    a, b = st.columns([1, 2])
    with a, kit.card("Calories"):
        over = bool(target) and kcal > target * 1.05
        sub = (f"{_n(target - kcal)} kcal left" if kcal <= target else f"{_n(kcal - target)} kcal over") if target \
            else "No target set"
        kit.rings([{"frac": kcal / target if target else 0, "colour": bad if over else good, "size": 150,
                    "centre": _n(kcal), "centre_sub": f"of {_n(target)}" if target else "kcal", "title": sub}])
    with b, kit.card("Macros"):
        items = []
        for k in ("protein", "carbs", "fat", "fibre"):
            v, goal = t.get(k) or 0, tg.get(k)
            items.append({"frac": v / goal if goal else 0, "colour": MACRO[k], "size": 104,
                          "centre": f"{v:.0f}g", "centre_sub": f"of {goal:.0f}g" if goal else "",
                          "title": LABELS[k],
                          "sub": (f"{goal - v:.0f} g to go" if v < goal else "target hit") if goal else ""})
        kit.rings(items)


def _add_form(day, meal):
    names = sorted({i["name"] for i in food.items()} | set(food.recent_names()))
    with st.form(f"fd_add_{day}_{meal}", clear_on_submit=True, border=False):
        a, b = st.columns([3, 1])
        pick = a.selectbox("Food", [""] + names, key=f"fd_pick_{day}_{meal}", accept_new_options=True,
                           placeholder="Type a food (new ones are remembered)")
        servings = b.number_input("Servings", 0.25, 100.0, 1.0, 0.25, key=f"fd_srv_{day}_{meal}")
        st.caption("Nutrition per serving: leave empty to use what's saved for that food.")
        cols = st.columns(5)
        nums = {k: cols[i].number_input(f"{LABELS[k]} ({UNIT[k]})", 0.0, 10000.0, None, key=f"fd_{k}_{day}_{meal}")
                for i, k in enumerate(food.NUTRIENTS)}
        if st.form_submit_button(f"Add to {meal}", icon=":material/add:", type="primary"):
            if not pick:
                st.error("Pick or type a food.")
                return
            try:
                food.log(pick, meal, servings, day, **nums)
                st.rerun()
            except food.FoodError as e:
                st.error(str(e))


def _meal_card(day, meal, these):
    kcal = sum(e["kcal"] or 0 for e in these)
    with kit.card():
        st.markdown(f"{MEAL_ICON[meal]} **{meal.capitalize()}** :gray[· {_n(kcal)} kcal]")
        if not these:
            st.caption("Nothing logged.")
        for e in these:
            x, y = st.columns([8, 1], vertical_alignment="center")
            macros = " · ".join(f"{(e[k] or 0):.0f} g {k}" for k in ("protein", "carbs", "fat"))
            x.markdown(f"{escape(e['name'])}" + (f" ×{e['servings']:g}" if e["servings"] != 1 else "")
                       + f" · {(e['kcal'] or 0):.0f} kcal  \n:gray[{macros}]")
            if y.button("", icon=":material/close:", key=f"fd_del_{e['id']}", help="Remove", type="tertiary"):
                undo.checkpoint(f"Removed {e['name']} from the diary")
                food.delete_entry(e["id"])
                st.rerun()
        x, y = st.columns(2)
        with x.popover("Add food", icon=":material/add:", width="stretch"):
            _add_form(day, meal)
        if y.button("Copy the day before", key=f"fd_copy_{day}_{meal}", icon=":material/content_copy:",
                    width="stretch", type="tertiary"):
            n = food.copy_meal(day - timedelta(days=1), day, meal)
            st.toast(f"Copied {n} item{'s' * (n != 1)}." if n else "Nothing to copy.")
            if n:
                st.rerun()


def _diary(day):
    _summary(day)
    rows = food.entries(day)
    for pair in (food.MEALS[:2], food.MEALS[2:]):
        cols = st.columns(2)
        for col, meal in zip(cols, pair):
            with col:
                _meal_card(day, meal, [e for e in rows if e["meal"] == meal])
    plans = [p for p in food.planned(day, day) if not p["logged"]]
    if plans:
        with kit.card("Planned for this day"):
            for p in plans:
                x, y = st.columns([6, 1], vertical_alignment="center")
                x.markdown(f"{p['meal'].capitalize()} · **{escape(p['name'])}**" + (f" ×{p['servings']:g}" if p["servings"] != 1 else ""))
                if y.button("Log it", key=f"fd_dlog_{p['id']}", icon=":material/check:", width="stretch"):
                    food.log_planned(p["id"])
                    st.rerun()


# --- Meal plan ---

def _plan_form(day, has_recipes):
    with st.form("fd_plan_add", clear_on_submit=True, border=False):
        pday = st.date_input("Day", day, key="fd_plan_day")
        meal = st.selectbox("Meal", food.MEALS, index=2, key="fd_plan_meal", format_func=str.capitalize)
        options = [""]
        if has_recipes:
            from venato.blocks import recipes
            options += [f"Recipe: {r['name']}" for r in recipes.all_recipes()]
        what = st.selectbox("What", options, accept_new_options=True, key="fd_plan_what",
                            placeholder="A recipe, or type anything")
        servings = st.number_input("Servings", 0.5, 50.0, 1.0, 0.5, key="fd_plan_srv")
        if st.form_submit_button("Plan it", icon=":material/add:", type="primary"):
            if not what:
                st.error("Say what the meal is.")
            else:
                rid, name = None, what
                if what.startswith("Recipe: ") and has_recipes:
                    from venato.blocks import recipes
                    r = recipes.find(what[8:])
                    rid, name = (r["id"], r["name"]) if r else (None, what[8:])
                food.plan(name, pday, meal, servings, rid)
                st.rerun()


def _planner(day):
    first = store.week_start_of(day)
    days = [first + timedelta(days=i) for i in range(7)]
    rows = food.planned(first, days[-1])
    has_recipes = blocks.is_on("recipes")
    grid = {}
    for p in rows:
        grid.setdefault((p["date"], p["meal"]), []).append(p)
    a, b, _ = st.columns([1, 2, 3], vertical_alignment="center")
    with a.popover("Plan a meal", icon=":material/add:", type="primary", width="stretch"):
        _plan_form(day, has_recipes)
    if has_recipes and b.button("Add this week's recipes to the shopping list", icon=":material/shopping_cart:"):
        from venato.blocks import recipes
        n = recipes.plan_to_shopping(first, days[-1])
        st.toast(f"Added {n} ingredients to the shopping list." if n else "No recipes planned this week.")
    st.caption(f"Week of {store.fmt_day(first, '%-d %B')}")
    today = store.local_today()
    cols = st.columns(7, gap="small")
    for col, d in zip(cols, days):
        with col, st.container(border=True, height="stretch"):
            kit.html(f"<div style='display:flex;gap:8px;align-items:center'>{kit.date_badge(d)}"
                     f"<span style='font-size:.85rem;font-weight:600'>{'Today' if d == today else f'{d:%a}'}</span></div>")
            items = [p for meal in food.MEALS for p in grid.get((d.isoformat(), meal), [])]
            if not items:
                st.caption("Nothing planned")
            for p in items:
                name = escape(p["name"]) + (f" ×{p['servings']:g}" if p["servings"] != 1 else "")
                st.markdown(f":gray[{p['meal'].capitalize()}]  \n" + (f"~~{name}~~" if p["logged"] else f"**{name}**"))
                x, y = st.columns(2, gap="small")
                if not p["logged"] and x.button("", icon=":material/check:", key=f"fd_plog_{p['id']}",
                                                help="Log it in the diary", type="tertiary"):
                    food.log_planned(p["id"])
                    st.rerun()
                if y.button("", icon=":material/close:", key=f"fd_pdel_{p['id']}",
                            help="Remove from the plan", type="tertiary"):
                    food.unplan(p["id"])
                    st.rerun()


# --- Trends ---

def _trends(today):
    first = today - timedelta(days=29)
    data = food.daily_totals(first, today)
    if not data:
        kit.empty("Log a few days to see trends.")
        return
    tg = food.targets()
    df = pd.DataFrame([{"date": pd.to_datetime(d), **v} for d, v in data.items()]).sort_values("date")
    avg = df[list(food.NUTRIENTS)].mean()
    hit = int(((df["kcal"] - tg["kcal"]).abs() <= tg["kcal"] * 0.1).sum()) if tg.get("kcal") else None
    kit.stats([
        {"label": "Average calories", "value": f"{avg['kcal']:,.0f}",
         "help": "A day, over the days you logged in the last 30"},
        {"label": "Average protein", "value": f"{avg['protein']:.0f} g"},
        {"label": "Days logged", "value": f"{len(df)} of 30"},
        {"label": "Days near your calorie target", "value": "–" if hit is None else str(hit),
         "help": "Within 10% of the target"},
    ])
    good, bad = kit.good_bad()
    a, b = st.columns(2)
    with a, kit.card("Calories per day"):
        colour = [bad if tg.get("kcal") and v > tg["kcal"] * 1.05 else kit.PALETTE[0] for v in df["kcal"]]
        fig = go.Figure(go.Bar(x=df["date"], y=df["kcal"], marker_color=colour,
                               hovertemplate="%{x|%a %-d %b}: %{y:,.0f} kcal<extra></extra>"))
        if tg.get("kcal"):
            fig.add_hline(y=tg["kcal"], line=dict(dash="dot", color="rgba(128,128,128,.7)"),
                          annotation_text="target", annotation_position="top left")
        fig.update_xaxes(tickformat="%-d %b")
        kit.chart(fig, "fd_tr_kcal")
    with b, kit.card("Macros per day (g)"):
        fig = go.Figure()
        for k in ("protein", "carbs", "fat"):
            fig.add_scatter(x=df["date"], y=df[k], name=LABELS[k], mode="lines", line=dict(color=MACRO[k], width=2.5),
                            hovertemplate=f"{LABELS[k]}: " + "%{y:.0f} g<extra></extra>")
        fig.update_xaxes(tickformat="%-d %b")
        fig.update_layout(hovermode="x unified")
        kit.chart(fig, "fd_tr_macros", legend=True)


# --- Your foods and targets ---

def _foods():
    rows = food.items()
    a, b = st.columns([3, 2])
    with a, kit.card("Your foods", "Nutrition per serving. Foods you log with numbers are saved here."):
        if rows:
            kit.table([{"Food": i["name"], "Serving": i["serving"] or "",
                        **{LABELS[k]: i[k] for k in food.NUTRIENTS}} for i in rows],
                      numbers={LABELS[k]: "%.0f" for k in food.NUTRIENTS}, height=min(420, 38 + 35 * len(rows)))
            with st.popover("Delete a food", icon=":material/delete:"):
                pick = st.selectbox("Food", [i["name"] for i in rows], key="fd_item_del")
                if st.button("Delete", key="fd_item_del_go", type="primary"):
                    item = food.find_item(pick)
                    undo.checkpoint(f"Deleted the food {pick}")
                    food.delete_item(item["id"])
                    st.rerun()
        else:
            kit.empty("No saved foods yet.")
        with st.expander("Add a food", icon=":material/add:"):
            with st.form("fd_item_add", clear_on_submit=True, border=False):
                x, y = st.columns([3, 2])
                name = x.text_input("Food")
                serving = y.text_input("Serving", placeholder="e.g. 1 slice (30 g)")
                cols = st.columns(5)
                nums = {k: cols[i].number_input(f"{LABELS[k]} ({UNIT[k]})", 0.0, 10000.0, None, key=f"fd_item_{k}")
                        for i, k in enumerate(food.NUTRIENTS)}
                if st.form_submit_button("Save food", type="primary"):
                    try:
                        food.save_item(name, serving or None, **nums)
                        st.rerun()
                    except food.FoodError as e:
                        st.error(str(e))
    with b, kit.card("Daily targets", "Leave one at 0 for no target."):
        tg = food.targets()
        new = {k: st.number_input(f"{LABELS[k]} ({UNIT[k]})", 0, 10000, int(tg[k] or 0), key=f"fd_tg_{k}")
               for k in food.NUTRIENTS}
        if any((new[k] or None) != (int(tg[k]) if tg[k] else None) for k in new):
            food.save_targets(**new)


# --- The page ---

def render_page():
    st.title("Food")
    has_food, has_recipes = blocks.is_on("food"), blocks.is_on("recipes")
    names = (["Today", "Meal plan"] if has_food else []) + (["Recipes", "Shopping list"] if has_recipes else []) \
        + (["Trends", "Foods & targets"] if has_food else [])
    tabs = dict(zip(names, st.tabs(names)))
    today = store.local_today()
    if has_food:
        with tabs["Today"]:
            day = _day_picker()
            _diary(day)
        with tabs["Meal plan"]:
            _planner(st.session_state.get("fd_day", today))
        with tabs["Trends"]:
            _trends(today)
        with tabs["Foods & targets"]:
            _foods()
    if has_recipes:
        from venato.ui import recipes
        with tabs["Recipes"]:
            recipes.recipes_tab()
        with tabs["Shopping list"]:
            recipes.shopping_tab()


def render_home():
    today = store.local_today()
    t, tg = food.totals(today), food.targets()
    st.markdown("**Food**")
    target = f" / {tg['kcal']:.0f}" if tg.get("kcal") else ""
    text = f"{t['kcal']:.0f}{target} kcal · {t['protein']:.0f} g protein today"
    plans = [p for p in food.planned(today, today) if not p["logged"]]
    if plans:
        text += " · next: " + ", ".join(f"{p['meal']} {p['name']}" for p in plans[:2])
    st.caption(text)
