"""The Recipes page (recipes and the shopping list) and its Home widget.
The data is in venato/blocks/recipes.py."""

from datetime import timedelta
from html import escape

import streamlit as st

from venato import blocks
from venato import store
from venato import undo
from venato.blocks import recipes as rc

OPEN = "rc_open"


def _shopping():
    rows = rc.shopping()
    with st.form("rc_shop_add", clear_on_submit=True, border=False):
        a, b = st.columns([5, 1], vertical_alignment="bottom")
        text = a.text_input("Add to the list", placeholder="e.g. 2 onions, milk, 500 g mince")
        if b.form_submit_button("Add", icon=":material/add:", width="stretch") and text.strip():
            for part in [p.strip() for p in text.split(",") if p.strip()]:
                rc.add_item(part)
            st.rerun()
    if not rows:
        st.caption("The shopping list is empty.")
    aisles = []
    for r in rows:
        if not r["done"] and r["aisle"] not in aisles:
            aisles.append(r["aisle"])
    for aisle in aisles:
        st.markdown(f"**{aisle}**")
        for r in [x for x in rows if x["aisle"] == aisle and not x["done"]]:
            _shop_row(r)
    done = [r for r in rows if r["done"]]
    if done:
        with st.expander(f"Ticked ({len(done)})"):
            for r in done:
                _shop_row(r)
            if st.button("Clear ticked items", key="rc_clear"):
                undo.checkpoint("Cleared the ticked shopping")
                rc.clear_done()
                st.rerun()
    if blocks.is_on("food") and st.button("Add the next 7 days' planned recipes", icon=":material/event:"):
        today = store.local_today()
        n = rc.plan_to_shopping(today, today + timedelta(days=6))
        st.success(f"Added {n} ingredients." if n else "No recipes planned in the next 7 days.")


def _shop_row(r):
    a, b = st.columns([10, 1], vertical_alignment="center")
    label = rc.line(r["qty"], r["unit"], r["item"]) + (f" · for {r['source']}" if r["source"] else "")
    new = a.checkbox(label, value=bool(r["done"]), key=f"rc_tick_{r['id']}")
    if new != bool(r["done"]):
        rc.tick(r["id"], new)
        st.rerun()
    if b.button("", icon=":material/close:", key=f"rc_rm_{r['id']}", help="Remove"):
        rc.remove_item(r["id"])
        st.rerun()


def _recipe_form(r=None):
    key = r["id"] if r else "new"
    ings = "\n".join(rc.line(i["qty"], i["unit"], i["item"]) for i in rc.ingredients(r["id"])) if r else ""
    with st.form(f"rc_form_{key}", clear_on_submit=not r):
        a, b, c, d = st.columns([4, 1, 1, 1])
        name = a.text_input("Name", r["name"] if r else "")
        servings = b.number_input("Serves", 1.0, 100.0, float(r["servings"]) if r else 2.0, 1.0)
        prep = c.number_input("Prep (min)", 0, 1440, int(r["prep_min"] or 0) if r else 0)
        cook = d.number_input("Cook (min)", 0, 1440, int(r["cook_min"] or 0) if r else 0)
        ingredients = st.text_area("Ingredients, one per line", ings, height=150,
                                   placeholder="200 g pasta\n2 onions\n1 tin chopped tomatoes")
        method = st.text_area("Method", (r["method"] or "") if r else "", height=150)
        a, b = st.columns(2)
        tags = a.text_input("Tags", (r["tags"] or "") if r else "", placeholder="e.g. quick, vegetarian")
        url = b.text_input("Link", (r["url"] or "") if r else "", placeholder="https://…")
        st.caption("Nutrition per serving (optional: the Food diary uses it when you log this recipe)")
        cols = st.columns(5)
        nut = {k: cols[i].number_input(k.capitalize() + (" (g)" if k != "kcal" else ""), 0.0, 10000.0,
                                       (r[k] if r else None), key=f"rc_{k}_{key}")
               for i, k in enumerate(rc.PER_SERVING)}
        if st.form_submit_button("Save recipe", type="primary"):
            try:
                rid = rc.save(name, ingredients.splitlines(), servings, method or None, tags or None, url or None,
                              None, prep or None, cook or None, recipe_id=r["id"] if r else None, **nut)
                st.session_state[OPEN] = rid
                st.rerun()
            except (rc.RecipeError, ValueError, ZeroDivisionError) as e:
                st.error(str(e))


def _recipe_view(r):
    st.subheader(r["name"], anchor=False)
    bits = [f"serves {r['servings']:g}", f"prep {r['prep_min']} min" if r["prep_min"] else "",
            f"cook {r['cook_min']} min" if r["cook_min"] else "", r["tags"] or ""]
    st.caption(" · ".join(b for b in bits if b))
    servings = st.number_input("Make it for", 0.5, 100.0, float(r["servings"]), 0.5, key=f"rc_for_{r['id']}")
    a, b = st.columns([1, 1])
    with a:
        st.markdown("**Ingredients**")
        st.markdown("\n".join(f"- {escape(rc.line(i['qty'], i['unit'], i['item']))}"
                              for i in rc.ingredients(r["id"], servings)) or "None yet.")
    with b:
        st.markdown("**Method**")
        st.markdown(escape(r["method"] or "No method yet.").replace("\n", "  \n"))
        if r["url"]:
            st.link_button("Open the original", r["url"], icon=":material/open_in_new:")
    if any(r[k] is not None for k in rc.PER_SERVING):
        st.caption("Per serving: " + ", ".join(f"{k} {r[k]:g}{'' if k == 'kcal' else ' g'}"
                                               for k in rc.PER_SERVING if r[k] is not None))
    c, d, e = st.columns(3)
    if c.button("Add to shopping list", key=f"rc_shop_{r['id']}", icon=":material/shopping_cart:"):
        n = rc.recipe_to_shopping(r["id"], servings)
        st.toast(f"Added {n} ingredients.")
    if blocks.is_on("food"):
        with d.popover("Plan it", icon=":material/event:"):
            from venato.blocks import food
            day = st.date_input("Day", store.local_today(), key=f"rc_plan_day_{r['id']}")
            meal = st.selectbox("Meal", food.MEALS, index=2, key=f"rc_plan_meal_{r['id']}")
            if st.button("Plan", key=f"rc_plan_go_{r['id']}", type="primary"):
                food.plan(r["name"], day, meal, servings, r["id"])
                st.toast(f"Planned for {meal} on {day:%a %-d %b}.")
    if e.button("Delete recipe", key=f"rc_del_{r['id']}", icon=":material/delete:"):
        undo.checkpoint(f"Deleted the recipe {r['name']}")
        rc.delete(r["id"])
        st.session_state.pop(OPEN, None)
        st.rerun()
    with st.expander("Edit"):
        _recipe_form(r)


def _recipes():
    query = st.text_input("Search recipes", key="rc_q", placeholder="name, tag or ingredient")
    rows = rc.all_recipes(query)
    left, right = st.columns([1, 2], gap="large")
    with left:
        if st.button("New recipe", icon=":material/add:", width="stretch"):
            st.session_state[OPEN] = "new"
        for r in rows:
            if st.button(r["name"], key=f"rc_pick_{r['id']}", width="stretch",
                         type="primary" if st.session_state.get(OPEN) == r["id"] else "secondary"):
                st.session_state[OPEN] = r["id"]
                st.rerun()
        if not rows:
            st.caption("No recipes yet." if not query else "None match.")
    with right:
        current = st.session_state.get(OPEN)
        if current == "new" or (not current and not rows):
            _recipe_form()
        elif current and rc.get(current):
            _recipe_view(rc.get(current))


def render_page():
    st.title("Recipes")
    tab_shop, tab_recipes = st.tabs(["Shopping list", "Recipes"])
    with tab_shop:
        _shopping()
    with tab_recipes:
        _recipes()


def render_home():
    rows = rc.shopping(include_done=False)
    st.markdown("**Shopping**")
    if not rows:
        st.caption("The shopping list is empty.")
        return
    st.caption(f"{len(rows)} to buy: " + ", ".join(rc.line(r["qty"], r["unit"], r["item"]) for r in rows[:8])
               + ("…" if len(rows) > 8 else ""))
