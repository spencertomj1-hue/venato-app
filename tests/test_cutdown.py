"""Cut down block: presets, add / total modes, limits, streaks, quitting, money, quick, tools."""

import importlib
from datetime import timedelta
from pathlib import Path

import pytest


@pytest.fixture
def cd(store):
    from venato import blocks, tools, quick
    importlib.reload(tools)
    importlib.reload(blocks)
    importlib.reload(quick)
    from venato.blocks import cutdown as module
    module = importlib.reload(module)
    blocks.save(blocks.chosen_keys() + ["cutdown"])
    return module


def test_presets_modes_and_streak(cd, store):
    today = store.local_today()
    caf = cd.find("caffeine")
    assert [p["name"] for p in cd.presets(caf["id"])][:2] == ["Coffee", "Espresso"]
    for back, amount in ((3, 100), (2, 500), (1, 300)):          # over the 400 mg limit two days ago
        cd.log(caf["id"], amount, today - timedelta(days=back))
    cd.log(caf["id"], 95, today)
    cd.log(caf["id"], 95, today)
    s = cd.status(caf, today)
    assert s["today"] == 190 and s["streak"] == 2 and not s["over_today"]
    screen = cd.find("screen time")
    cd.log(screen["id"], 4, today)
    cd.log(screen["id"], 5, today)                               # a day's total: replaced, not added
    assert cd.day_total(screen["id"], today) == 5 and cd.status(screen, today)["over_today"]
    with pytest.raises(cd.CutError):
        cd.log(caf["id"], -1)


def test_quitting_and_money(cd, store):
    today = store.local_today()
    smoke = cd.find("smoking")
    cd.update_tracker(smoke["id"], quit_since=(today - timedelta(days=10)).isoformat(), cost=0.7, baseline=10)
    cd.log(smoke["id"], 2, today - timedelta(days=4))
    s = cd.status(cd.find("smoking"), today)
    assert s["days_free"] == 3 and s["saved"] == pytest.approx((10 * 10 - 2) * 0.7)
    alc = cd.find("alcohol")
    cd.update_tracker(alc["id"], cost=2.5)
    cd.log(alc["id"], 2.3 * 2, today)
    s = cd.status(cd.find("alcohol"), today)
    assert s["week"] == pytest.approx(4.6) and s["spent_month"] == pytest.approx(11.5)


def test_quick_and_tools(cd, store):
    from venato import quick
    today = store.local_today()
    assert "Coffee" in quick.handle("had a coffee").reply
    assert "2 × Pint" in quick.handle("drank 2 pints").reply
    assert "3 × Espresso" in quick.handle("3 espressos").reply
    quick.handle("smoked 3")
    quick.handle("screen time 4.5h")
    assert cd.day_total(cd.find("smoking")["id"], today) == 3
    assert cd.day_total(cd.find("screen time")["id"], today) == 4.5
    assert quick.handle("had a great day") is None
    assert "Logged 47" in cd.tool_log(preset="Tea").text
    cd.tool_add("Sugar", "g", daily_limit=30)
    assert "Sugar" in cd.tool_status().text
    assert "quit" in cd.tool_limit("alcohol", goal="quit").text or cd.find("alcohol")["goal"] == "quit"
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=60).run()
    at.sidebar.radio[0].set_value("Cut down").run()
    assert not at.exception
