"""Food and Recipes blocks: diary, targets, library, meal plan, recipes, shopping."""

import importlib
from datetime import date, timedelta

import pytest


@pytest.fixture
def food(store):
    from venato import blocks, tools, quick
    importlib.reload(tools)
    importlib.reload(blocks)
    importlib.reload(quick)
    from venato.blocks import food as f, recipes as r
    f, r = importlib.reload(f), importlib.reload(r)
    blocks.save(blocks.chosen_keys() + ["food", "recipes"])
    return f, r


def test_diary_library_and_totals(food, store):
    f, _ = food
    day = date(2026, 11, 4)
    f.log("Porridge", "breakfast", 1, day, kcal=350, protein=12, carbs=55, fat=8)     # remembered per serving
    f.log("Porridge", "breakfast", 2, day + timedelta(days=1))                         # from the library: ×2
    e = f.entries(day + timedelta(days=1))[0]
    assert (e["kcal"], e["protein"]) == (700, 24)
    f.update_entry(e["id"], servings=1)                                                 # numbers scale with it
    assert f.get_entry(e["id"])["kcal"] == 350
    assert f.totals(day)["kcal"] == 350 and f.find_item("porridge")["kcal"] == 350
    assert f.copy_meal(day, day + timedelta(days=2), "breakfast") == 1
    with pytest.raises(f.FoodError):
        f.log("Pizza", "elevenses", 1, day)
    with pytest.raises(f.FoodError):
        f.log("Pizza", "lunch", 1, day, kcal=-5)
    assert f.meal_now(store.local_now().replace(hour=8)) == "breakfast"


def test_recipes_parsing_and_scaling(food, store):
    _, r = food
    assert r.parse("200 g pasta") == (200, "g", "pasta")
    assert r.parse("1/2 tsp salt") == (0.5, "tsp", "salt")
    assert r.parse("1 1/2 cups milk") == (1.5, "cup", "milk")
    assert r.parse("2 onions") == (2, "", "onions")
    assert r.parse("salt and pepper") == (None, "", "salt and pepper")
    assert r.parse("500ml stock") == (500, "ml", "stock")
    rid = r.save("Pasta bake", ["400 g pasta", "2 onions", "1 tin tomatoes"], servings=4, kcal=550, protein=20)
    assert [r.line(i["qty"], i["unit"], i["item"]) for i in r.ingredients(rid, 2)] == ["200g pasta", "1 onions", "0.5 tin tomatoes"]
    with pytest.raises(r.RecipeError):
        r.save("pasta bake", ["1 egg"])                                                 # names are unique
    with pytest.raises(r.RecipeError):
        r.save("Bad link", [], url="javascript:alert(1)")
    assert r.find("pasta")["name"] == "Pasta bake" and r.all_recipes("tomatoes")


def test_plan_logging_and_shopping(food, store):
    f, r = food
    today = store.local_today()
    rid = r.save("Chilli", ["500 g mince", "1 onion", "2 tins beans"], servings=4, kcal=600, protein=40)
    pid = f.plan("Chilli", today, "dinner", 2, rid)
    r.add_item("1 onion")
    assert r.plan_to_shopping(today, today) == 3
    items = {i["item"]: (i["qty"], i["unit"], i["aisle"]) for i in r.shopping()}
    assert items["onion"] == (1.5, "", "Fruit & veg")                                   # merged: 1 + 2/4 × 1
    assert items["mince"] == (250, "g", "Meat & fish") and items["beans"][2] == "Tins, jars & dry"
    e = f.log_planned(pid)
    assert e["kcal"] == 1200 and f.planned(today, today)[0]["logged"] == 1
    sid = r.shopping()[0]["id"]
    r.tick(sid)
    assert r.clear_done() == 1


def test_tools_and_quick(food, store):
    f, r = food
    from venato import quick
    assert "estimated" in f.tool_log("Chicken caesar salad", "lunch", kcal=480, protein=35, carbs=20, fat=28,
                                     estimated=True).text
    f.save_item("Banana", "1 medium", kcal=105, protein=1.3, carbs=27, fat=0.4)
    q = quick.handle("ate a banana")
    assert q and "Banana" in q.reply
    assert quick.handle("ate a mystery stew") is None                                    # unknown: Claude estimates
    q = quick.handle("add milk, eggs and bread to the shopping list")
    assert q and {i["item"] for i in r.shopping()} == {"milk", "eggs", "bread"}
    assert "Dairy & eggs" in r.tool_shop_list().text
    assert "Banana" in f.tool_day().text and "Eaten today" in f._context()


def test_pages(food, store):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    f, r = food
    rid = r.save("Chilli", ["500 g mince"], servings=4, kcal=600)
    f.plan("Chilli", store.local_today(), "dinner", 2, rid)
    f.log("Toast", "breakfast", 1, kcal=150)
    r.add_item("milk")
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=60).run()
    for page in ("Food", "Recipes", "Home"):
        at.sidebar.radio[0].set_value(page).run()
        assert not at.exception, page
    at.session_state["rc_open"] = rid
    at.sidebar.radio[0].set_value("Recipes").run()
    assert not at.exception
