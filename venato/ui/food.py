"""The Food page (diary, meal planner, your foods, trends) and its Home widget.
The data is in venato/blocks/food.py."""

from datetime import timedelta
from html import escape

import pandas as pd
import plotly.express as px
import streamlit as st

from venato import blocks
from venato import store
from venato import undo
from venato.blocks import food

LABELS = {"kcal": "Calories", "protein": "Protein", "carbs": "Carbs", "fat": "Fat", "fibre": "Fibre"}
UNIT = {"kcal": "kcal", "protein": "g", "carbs": "g", "fat": "g", "fibre": "g"}


def _bars(t, tg):
    rows = []
    for k in food.NUTRIENTS:
        target = tg.get(k)
        val = t.get(k) or 0
        pct = min(100, 100 * val / target) if target else 0
        over = target and val > target * 1.05
        rows.append(f'<div class="fd-row"><span class="fd-k">{LABELS[k]}</span>'
                    f'<span class="fd-bar"><i style="width:{pct:.0f}%" class="{"over" if over else ""}"></i></span>'
                    f'<span class="fd-v">{val:.0f}{"" if k == "kcal" else " g"}'
                    f'{f" / {target:.0f}" if target else ""}</span></div>')
    st.html("""<style>
      .fd { display: grid; gap: 6px; }
      .fd-row { display: grid; grid-template-columns: 5.5em 1fr 8.5em; align-items: center; gap: 10px; font-size: 0.86rem; }
      .fd-bar { height: 8px; border-radius: 999px; background: rgba(128,128,128,.18); overflow: hidden; }
      .fd-bar i { display: block; height: 100%; border-radius: 999px; background: #2e9e6a; }
      .fd-bar i.over { background: #E53935; }
      .fd-v { text-align: right; font-variant-numeric: tabular-nums; }
    </style><div class="fd">""" + "".join(rows) + "</div>")


def _add_form(day, meal):
    names = sorted({i["name"] for i in food.items()} | set(food.recent_names()))
    with st.form(f"fd_add_{day}_{meal}", clear_on_submit=True, border=False):
        a, b = st.columns([4, 1])
        pick = a.selectbox("Food", [""] + names, key=f"fd_pick_{day}_{meal}", accept_new_options=True,
                           placeholder="Type a food (new ones are remembered)")
        servings = b.number_input("Servings", 0.25, 100.0, 1.0, 0.25, key=f"fd_srv_{day}_{meal}")
        cols = st.columns(5)
        nums = {k: cols[i].number_input(f"{LABELS[k]} ({UNIT[k]})", 0.0, 10000.0, None, key=f"fd_{k}_{day}_{meal}",
                                        placeholder="from your foods") for i, k in enumerate(food.NUTRIENTS)}
        if st.form_submit_button(f"Add to {meal}", icon=":material/add:"):
            if not pick:
                st.error("Pick or type a food.")
                return
            try:
                food.log(pick, meal, servings, day, **nums)
                st.rerun()
            except food.FoodError as e:
                st.error(str(e))


def _diary(day):
    t, tg = food.totals(day), food.targets()
    _bars(t, tg)
    rows = food.entries(day)
    for meal in food.MEALS:
        these = [e for e in rows if e["meal"] == meal]
        kcal = sum(e["kcal"] or 0 for e in these)
        with st.expander(f"**{meal.capitalize()}** · {kcal:.0f} kcal", expanded=bool(these) or meal == food.meal_now()):
            for e in these:
                a, b = st.columns([8, 1], vertical_alignment="center")
                macros = " · ".join(f"{(e[k] or 0):.0f}{UNIT[k] if k != 'kcal' else ' kcal'} {'' if k == 'kcal' else k}"
                                    for k in ("kcal", "protein", "carbs", "fat"))
                a.markdown(f"{escape(e['name'])} ×{e['servings']:g}  \n:gray[{macros}]")
                if b.button("", icon=":material/delete:", key=f"fd_del_{e['id']}", help="Remove"):
                    undo.checkpoint(f"Removed {e['name']} from the diary")
                    food.delete_entry(e["id"])
                    st.rerun()
            _add_form(day, meal)
            if st.button(f"Copy the day before's {meal}", key=f"fd_copy_{day}_{meal}", type="tertiary"):
                n = food.copy_meal(day - timedelta(days=1), day, meal)
                st.toast(f"Copied {n} item{'s' * (n != 1)}." if n else "Nothing to copy.")
                if n:
                    st.rerun()


def _planner(day):
    first = store.week_start_of(day)
    days = [first + timedelta(days=i) for i in range(7)]
    rows = food.planned(first, days[-1])
    has_recipes = blocks.is_on("recipes")
    grid = {(p["date"], p["meal"]): [] for p in rows}
    for p in rows:
        grid[(p["date"], p["meal"])].append(p)
    for d in days:
        with st.container(border=True):
            st.markdown(f"**{store.fmt_day(d, '%A %-d %b')}**")
            cols = st.columns(4)
            for i, meal in enumerate(food.MEALS):
                with cols[i]:
                    st.caption(meal.capitalize())
                    for p in grid.get((d.isoformat(), meal), []):
                        a, b, c = st.columns([5, 1, 1], vertical_alignment="center")
                        a.markdown(("~~" if p["logged"] else "") + f"{escape(p['name'])} ×{p['servings']:g}"
                                   + ("~~" if p["logged"] else ""))
                        if not p["logged"] and b.button("", icon=":material/check:", key=f"fd_plog_{p['id']}",
                                                        help="Log it in the diary"):
                            food.log_planned(p["id"])
                            st.rerun()
                        if c.button("", icon=":material/close:", key=f"fd_pdel_{p['id']}", help="Remove from the plan"):
                            food.unplan(p["id"])
                            st.rerun()
    with st.form("fd_plan_add", clear_on_submit=True):
        st.markdown("**Plan a meal**")
        a, b, c, d = st.columns([2, 2, 3, 1])
        pday = a.date_input("Day", day, key="fd_plan_day")
        meal = b.selectbox("Meal", food.MEALS, index=2, key="fd_plan_meal")
        options = [""]
        if has_recipes:
            from venato.blocks import recipes
            options += [f"Recipe: {r['name']}" for r in recipes.all_recipes()]
        what = c.selectbox("What", options, accept_new_options=True, key="fd_plan_what",
                           placeholder="A recipe, or type anything")
        servings = d.number_input("Servings", 0.5, 50.0, 1.0, 0.5, key="fd_plan_srv")
        if st.form_submit_button("Plan it", icon=":material/add:"):
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
    if has_recipes and st.button("Add this week's recipes to the shopping list", icon=":material/shopping_cart:"):
        from venato.blocks import recipes
        n = recipes.plan_to_shopping(first, days[-1])
        st.success(f"Added {n} ingredients to the shopping list." if n else "No recipes planned this week.")


def _foods():
    rows = food.items()
    st.caption("Your foods, with nutrition per serving. New foods you log with numbers are added here.")
    if rows:
        df = pd.DataFrame([{"Food": i["name"], "Serving": i["serving"] or "", **{LABELS[k]: i[k] for k in food.NUTRIENTS}}
                           for i in rows])
        st.dataframe(df, hide_index=True, width="stretch")
    with st.form("fd_item_add", clear_on_submit=True):
        a, b = st.columns([3, 2])
        name = a.text_input("Food")
        serving = b.text_input("Serving", placeholder="e.g. 1 slice (30 g)")
        cols = st.columns(5)
        nums = {k: cols[i].number_input(f"{LABELS[k]} ({UNIT[k]})", 0.0, 10000.0, None, key=f"fd_item_{k}")
                for i, k in enumerate(food.NUTRIENTS)}
        if st.form_submit_button("Save food"):
            try:
                food.save_item(name, serving or None, **nums)
                st.rerun()
            except food.FoodError as e:
                st.error(str(e))
    if rows:
        with st.expander("Delete a food"):
            pick = st.selectbox("Food", [i["name"] for i in rows], key="fd_item_del")
            if st.button("Delete", key="fd_item_del_go"):
                item = food.find_item(pick)
                undo.checkpoint(f"Deleted the food {pick}")
                food.delete_item(item["id"])
                st.rerun()


def _trends(day):
    first = day - timedelta(days=29)
    data = food.daily_totals(first, day)
    if not data:
        st.caption("Log a few days to see trends.")
        return
    df = pd.DataFrame([{"date": d, **v} for d, v in data.items()])
    df["date"] = pd.to_datetime(df["date"])
    tg = food.targets()
    fig = px.bar(df, x="date", y="kcal", title="Calories per day", labels={"kcal": "kcal", "date": ""})
    if tg.get("kcal"):
        fig.add_hline(y=tg["kcal"], line_dash="dot", annotation_text="target")
    fig.update_xaxes(tickformat="%-d %b")
    st.plotly_chart(fig, width="stretch")
    fig = px.line(df, x="date", y=["protein", "carbs", "fat"], markers=True, title="Macros per day (g)",
                  labels={"value": "g", "variable": "", "date": ""})
    fig.update_xaxes(tickformat="%-d %b")
    st.plotly_chart(fig, width="stretch")
    avg = df[list(food.NUTRIENTS)].mean()
    st.caption("Daily average over the days logged: " + ", ".join(
        f"{LABELS[k].lower()} {avg[k]:.0f}{'' if k == 'kcal' else ' g'}" for k in food.NUTRIENTS))


def _targets():
    tg = food.targets()
    cols = st.columns(5)
    new = {k: cols[i].number_input(f"{LABELS[k]} ({UNIT[k]})", 0, 10000, int(tg[k] or 0), key=f"fd_tg_{k}")
           for i, k in enumerate(food.NUTRIENTS)}
    if any((new[k] or None) != (int(tg[k]) if tg[k] else None) for k in new):
        food.save_targets(**new)
    st.caption("Leave one at 0 for no target.")


def render_page():
    st.title("Food")
    today = store.local_today()
    day = st.date_input("Day", today, key="fd_day")
    tabs = st.tabs(["Diary", "Meal plan", "My foods", "Trends", "Targets"])
    with tabs[0]:
        _diary(day)
    with tabs[1]:
        _planner(day)
    with tabs[2]:
        _foods()
    with tabs[3]:
        _trends(today)
    with tabs[4]:
        _targets()


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
