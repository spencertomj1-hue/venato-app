"""The Recipes and Shopping list tabs (on the Food page) and the Shopping Home widget.
The data is in venato/blocks/recipes.py."""

from datetime import timedelta
from html import escape

import streamlit as st

from venato import blocks
from venato import store
from venato import undo
from venato.blocks import recipes as rc
from venato.ui import kit

OPEN = "rc_open"
AISLE_ICON = {"Fruit & veg": ":material/nutrition:", "Meat & fish": ":material/set_meal:",
              "Dairy & eggs": ":material/egg:", "Bakery": ":material/bakery_dining:",
              "Frozen": ":material/ac_unit:", "Drinks": ":material/local_drink:",
              "Household": ":material/cleaning_services:"}


# --- Shopping list ---

def _shop_row(r):
    a, b = st.columns([10, 1], vertical_alignment="center")
    label = rc.line(r["qty"], r["unit"], r["item"]) + (f" · :gray[for {r['source']}]" if r["source"] else "")
    new = a.checkbox(label, value=bool(r["done"]), key=f"rc_tick_{r['id']}")
    if new != bool(r["done"]):
        rc.tick(r["id"], new)
        st.rerun()
    if b.button("", icon=":material/close:", key=f"rc_rm_{r['id']}", help="Remove", type="tertiary"):
        rc.remove_item(r["id"])
        st.rerun()


def shopping_tab():
    rows = rc.shopping()
    todo = [r for r in rows if not r["done"]]
    done = [r for r in rows if r["done"]]
    with st.form("rc_shop_add", clear_on_submit=True, border=False):
        a, b = st.columns([5, 1], vertical_alignment="bottom")
        text = a.text_input("Add to the list", placeholder="e.g. 2 onions, milk, 500 g mince")
        if b.form_submit_button("Add", icon=":material/add:", width="stretch", type="primary") and text.strip():
            for part in [p.strip() for p in text.split(",") if p.strip()]:
                rc.add_item(part)
            st.rerun()
    a, b = st.columns([3, 2], vertical_alignment="center")
    a.caption(f"{len(todo)} to buy" + (f" · {len(done)} ticked" if done else "") + " · grouped by aisle")
    if blocks.is_on("food") and b.button("Add the next 7 days' planned recipes", icon=":material/event:",
                                         width="stretch"):
        today = store.local_today()
        n = rc.plan_to_shopping(today, today + timedelta(days=6))
        st.toast(f"Added {n} ingredients." if n else "No recipes planned in the next 7 days.")
        if n:
            st.rerun()
    if not todo:
        kit.empty("Nothing to buy. Add things above, or from a recipe.", ":material/shopping_cart:")
    aisles = list(dict.fromkeys(r["aisle"] for r in todo))
    cols = st.columns(3)
    for i, aisle in enumerate(aisles):
        with cols[i % 3]:
            items = [x for x in todo if x["aisle"] == aisle]
            with st.container(border=True):
                st.markdown(f"{AISLE_ICON.get(aisle, ':material/shopping_basket:')} **{aisle}** :gray[· {len(items)}]")
                for r in items:
                    _shop_row(r)
    if done:
        with st.expander(f"Ticked ({len(done)})", icon=":material/done_all:"):
            for r in done:
                _shop_row(r)
            if st.button("Clear ticked items", key="rc_clear", icon=":material/delete_sweep:"):
                undo.checkpoint("Cleared the ticked shopping")
                rc.clear_done()
                st.rerun()


# --- Recipes ---

def _recipe_form(r=None):
    key = r["id"] if r else "new"
    ings = "\n".join(rc.line(i["qty"], i["unit"], i["item"]) for i in rc.ingredients(r["id"])) if r else ""
    with st.form(f"rc_form_{key}", clear_on_submit=not r, border=False):
        a, b, c, d = st.columns([4, 1, 1, 1])
        name = a.text_input("Name", r["name"] if r else "")
        servings = b.number_input("Serves", 1.0, 100.0, float(r["servings"]) if r else 2.0, 1.0)
        prep = c.number_input("Prep (min)", 0, 1440, int(r["prep_min"] or 0) if r else 0)
        cook = d.number_input("Cook (min)", 0, 1440, int(r["cook_min"] or 0) if r else 0)
        a, b = st.columns(2)
        ingredients = a.text_area("Ingredients, one per line", ings, height=200,
                                  placeholder="200 g pasta\n2 onions\n1 tin chopped tomatoes")
        method = b.text_area("Method", (r["method"] or "") if r else "", height=200)
        a, b = st.columns(2)
        tags = a.text_input("Tags", (r["tags"] or "") if r else "", placeholder="e.g. quick, vegetarian")
        url = b.text_input("Link", (r["url"] or "") if r else "", placeholder="https://…")
        st.caption("Nutrition per serving (optional: the Food diary uses it when you log this recipe)")
        cols = st.columns(5)
        nut = {k: cols[i].number_input(k.capitalize() + (" (g)" if k != "kcal" else ""), 0.0, 10000.0,
                                       (r[k] if r else None), key=f"rc_{k}_{key}")
               for i, k in enumerate(rc.PER_SERVING)}
        if st.form_submit_button("Save recipe", type="primary", icon=":material/save:"):
            try:
                rid = rc.save(name, ingredients.splitlines(), servings, method or None, tags or None, url or None,
                              None, prep or None, cook or None, recipe_id=r["id"] if r else None, **nut)
                st.session_state[OPEN] = rid
                st.rerun()
            except (rc.RecipeError, ValueError, ZeroDivisionError) as e:
                st.error(str(e))


def _tags(r):
    return [t.strip() for t in (r["tags"] or "").split(",") if t.strip()]


def _facts(r):
    mins = (r["prep_min"] or 0) + (r["cook_min"] or 0)
    bits = [f"serves {r['servings']:g}"] + ([f"{mins} min"] if mins else []) \
        + ([f"{r['kcal']:.0f} kcal"] if r["kcal"] is not None else [])
    return " · ".join(bits)


def _recipe_view(r):
    if st.button("All recipes", icon=":material/arrow_back:", type="tertiary", key="rc_back"):
        st.session_state.pop(OPEN, None)
        st.rerun()
    st.subheader(r["name"], anchor=False)
    st.caption(_facts(r) + (f" · prep {r['prep_min']} min, cook {r['cook_min']} min"
                            if r["prep_min"] and r["cook_min"] else ""))
    names = sorted({t for x in rc.all_recipes() for t in _tags(x)})
    tc = kit.colours(names)
    kit.pills([(t, tc[t]) for t in _tags(r)])
    a, b = st.columns([2, 3])
    with a, kit.card("Ingredients"):
        servings = st.number_input("Make it for", 0.5, 100.0, float(r["servings"]), 0.5, key=f"rc_for_{r['id']}")
        st.markdown("\n".join(f"- {escape(rc.line(i['qty'], i['unit'], i['item']))}"
                              for i in rc.ingredients(r["id"], servings)) or "None yet.")
        if st.button("Add to shopping list", key=f"rc_shop_{r['id']}", icon=":material/shopping_cart:",
                     width="stretch"):
            n = rc.recipe_to_shopping(r["id"], servings)
            st.toast(f"Added {n} ingredients.")
    with b, kit.card("Method"):
        steps = [s.strip() for s in (r["method"] or "").splitlines() if s.strip()]
        if steps:
            st.markdown("\n".join(f"{i + 1}. {escape(s)}" for i, s in enumerate(steps)))
        else:
            st.caption("No method yet.")
        if r["url"]:
            st.link_button("Open the original", r["url"], icon=":material/open_in_new:")
        if any(r[k] is not None for k in rc.PER_SERVING):
            st.caption("Per serving: " + " · ".join(f"{k} {r[k]:g}{'' if k == 'kcal' else ' g'}"
                                                    for k in rc.PER_SERVING if r[k] is not None))
    c, d, _ = st.columns([1, 1, 2])
    if blocks.is_on("food"):
        with c.popover("Plan it", icon=":material/event:", width="stretch"):
            from venato.blocks import food
            day = st.date_input("Day", store.local_today(), key=f"rc_plan_day_{r['id']}")
            meal = st.selectbox("Meal", food.MEALS, index=2, key=f"rc_plan_meal_{r['id']}", format_func=str.capitalize)
            if st.button("Plan", key=f"rc_plan_go_{r['id']}", type="primary"):
                food.plan(r["name"], day, meal, servings, r["id"])
                st.toast(f"Planned for {meal} on {store.fmt_day(day, '%a %-d %b')}.")
    with d.popover("Delete", icon=":material/delete:", width="stretch"):
        st.warning(f"Delete {r['name']}? (Undo can bring it back.)")
        if st.button("Delete recipe", key=f"rc_del_{r['id']}", type="primary"):
            undo.checkpoint(f"Deleted the recipe {r['name']}")
            rc.delete(r["id"])
            st.session_state.pop(OPEN, None)
            st.rerun()
    with st.expander("Edit", icon=":material/edit:"):
        _recipe_form(r)


def _gallery(rows, query):
    if not rows:
        kit.empty("No recipes yet: add your first one." if not query else "No recipes match.", ":material/menu_book:")
        return
    names = sorted({t for x in rc.all_recipes() for t in _tags(x)})
    tc = kit.colours(names)
    cols = st.columns(3)
    for i, r in enumerate(rows):
        with cols[i % 3], st.container(border=True):
            st.markdown(f"**{escape(r['name'])}**")
            st.caption(_facts(r))
            kit.pills([(t, tc[t]) for t in _tags(r)])
            if st.button("Open", key=f"rc_pick_{r['id']}", icon=":material/arrow_forward:", width="stretch"):
                st.session_state[OPEN] = r["id"]
                st.rerun()


def recipes_tab():
    current = st.session_state.get(OPEN)
    if current and current != "new" and rc.get(current):
        _recipe_view(rc.get(current))
        return
    a, b = st.columns([4, 1], vertical_alignment="bottom")
    query = a.text_input("Search recipes", key="rc_q", placeholder="Search by name, tag or ingredient",
                         label_visibility="collapsed")
    if b.button("New recipe", icon=":material/add:", width="stretch", type="primary"):
        st.session_state[OPEN] = "new"
        st.rerun()
    if current == "new":
        with kit.card("New recipe", stretch=False):
            _recipe_form()
            if st.button("Cancel", key="rc_new_cancel", type="tertiary"):
                st.session_state.pop(OPEN, None)
                st.rerun()
    _gallery(rc.all_recipes(query), query)


def render_page():
    """Recipes have no page of their own any more: they're tabs on the Food page."""
    from venato.ui import food
    food.render_page()


def render_home():
    rows = rc.shopping(include_done=False)
    st.markdown("**Shopping**")
    if not rows:
        st.caption("The shopping list is empty.")
        return
    st.caption(f"{len(rows)} to buy: " + ", ".join(rc.line(r["qty"], r["unit"], r["item"]) for r in rows[:8])
               + ("…" if len(rows) > 8 else ""))
