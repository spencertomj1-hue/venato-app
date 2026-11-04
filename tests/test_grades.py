"""Grades block: averages, secured marks, what's needed, year weighting, UK / US, tools, quick."""

import importlib
from pathlib import Path

import pytest


@pytest.fixture
def gr(store):
    from venato import blocks, tools, quick
    importlib.reload(tools)
    importlib.reload(blocks)
    importlib.reload(quick)
    from venato.blocks import grades as module
    module = importlib.reload(module)
    blocks.save(blocks.chosen_keys() + ["grades"])
    return module


def test_module_maths(gr, store):
    mid = gr.add_module("Quantum Mechanics", 20, "Year 2", target=70, code="QM")
    gr.add_assessment(mid, "Coursework", 30, 80)
    gr.add_assessment(mid, "Midterm", 20, 60)
    gr.add_assessment(mid, "Exam", 50)
    n = gr.module_numbers(gr.get_module(mid))
    assert n["average"] == pytest.approx(72) and n["secured"] == pytest.approx(36)
    assert n["needed"] == pytest.approx(68) and n["status"] == "possible"     # (70 - 36) / 50%
    with pytest.raises(gr.GradeError):
        gr.add_assessment(mid, "Extra", 10)                                    # over 100% of the module
    with pytest.raises(gr.GradeError):
        gr.add_assessment(mid, "Bad", 5, 120)


def test_overall_years_and_systems(gr, store):
    a = gr.add_module("A", 20, "Year 2")
    gr.add_assessment(a, "Exam", 100, 60)
    b = gr.add_module("B", 20, "Year 3")
    gr.add_assessment(b, "Exam", 100, 75)
    gr.save_settings("UK", {"Year 2": 1, "Year 3": 2})
    o = gr.overall()
    assert o["degree"] == pytest.approx((60 + 2 * 75) / 3) and gr.classification(o["degree"]) == "First"
    assert gr.classification(59.9) == "2:2" and gr.letter(88) == ("B+", 3.3)
    gr.save_settings("US")
    assert "GPA" in gr.describe(o["degree"], o["gpa"])
    gr.update_module(a, final=65)
    assert gr.module_numbers(gr.get_module(a))["projected"] == 65


def test_tools_quick_and_page(gr, store):
    from venato import quick
    gr.tool_add_module("ACP", 15, "Year 2", 70)
    gr.tool_add_grade("acp", "Coursework", weight=40)
    assert "Saved" in quick.handle("got 68 in acp coursework").reply
    assert gr.assessments(gr.find_module("ACP")["id"])[0]["mark"] == 68
    assert "needs" in gr.tool_needed("ACP").text and "Overall" in gr.tool_summary().text
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=60).run()
    at.sidebar.radio[0].set_value("Grades").run()
    assert not at.exception
