"""Home's hidden grid (venato/home_layout.py): the default, packing into rows, skipping, the arrange
operations and undo; then Home itself (AppTest): a blank install, every widget hidden, arrange mode,
Needs you and its one-time assistant card."""

import json
from datetime import date, timedelta
from pathlib import Path

from streamlit.testing.v1 import AppTest

from venato import home_layout as hl

APP = str(Path(__file__).resolve().parents[1] / "app.py")

# What a full install offers: every widget key with its default size.
ALL = {"timetable_today": "l", "ask": "s", "needs_you": "s", "todos": "s", "deadlines": "s", "goals": "m",
       "habits": "m", "journal": "s", "focus": "s", "modules": "m"}


# --- the layout itself (pure) ---

def test_default_layout_is_essentials():
    assert hl.default() == [{"w": "timetable_today", "size": "l"}, {"stack": ["ask", "needs_you", "todos"], "size": "s"}]
    assert hl.normalise(None, ALL) == hl.default()                       # no saved key: the default
    assert hl.normalise("rubbish", ALL) == hl.default()
    rows = hl.pack(hl.default())
    assert [hl.widths(r) for r in rows] == [[8, 4]]                       # timetable ⅔ | the stack ⅓
    assert "deadlines" not in hl.keys(hl.default())                       # the rest are hidden until added
    assert hl.hidden(hl.default(), ALL) == ["deadlines", "goals", "habits", "journal", "focus", "modules"]


def test_custom_list_packs_into_rows_and_widths():
    cells = [{"w": "todos", "size": "s"}, {"w": "goals", "size": "m"}, {"w": "habits", "size": "s"},
             {"w": "journal", "size": "full"}, {"w": "focus", "size": "l"}]
    rows = hl.pack(cells)
    assert [[c.get("w") for c in r] for r in rows] == [["todos", "goals"], ["habits"], ["journal"], ["focus"]]
    assert [hl.widths(r) for r in rows] == [[4, 6], [4], [12], [8]]
    assert [hl.spec(r) for r in rows] == [[4, 6, 2], [4, 8], [12], [8, 4]]   # a short row gets a spacer


def test_over_wide_rows_wrap():
    cells = [{"w": k, "size": "m"} for k in ("todos", "goals", "habits")] + [{"w": "focus", "size": "l"},
                                                                              {"w": "journal", "size": "s"}]
    assert [[c["w"] for c in r] for r in hl.pack(cells)] == [["todos", "goals"], ["habits"], ["focus", "journal"]]
    assert [[c["w"] for c in r] for r in hl.pack([{"w": "a", "size": "l"}, {"w": "b", "size": "m"}])] == [["a"], ["b"]]


def test_unknown_or_disabled_widgets_skipped():
    saved = [{"w": "money", "size": "m"}, {"w": "todos", "size": "huge"}, {"w": "todos", "size": "s"},
             {"stack": ["ask", "gone", "needs_you"], "size": "s"}, {"stack": ["gone"], "size": "m"},
             {"nonsense": 1}, "todos", {"stack": ["habits"], "size": "m"}]
    available = {k: v for k, v in ALL.items() if k != "ask"}              # e.g. the assistant is off
    assert hl.normalise(saved, available) == [{"w": "todos", "size": "s"},          # bad size: its default
                                              {"w": "needs_you", "size": "s"},       # a stack of one is a widget
                                              {"w": "habits", "size": "m"}]
    assert hl.normalise([], ALL) == []                                    # every widget hidden stays so


def test_move_and_swap():
    cells = [{"w": "a", "size": "s"}, {"w": "b", "size": "m"}, {"w": "c", "size": "l"}]
    assert hl.keys(hl.move(cells, "a", "c")) == ["b", "c", "a"]           # forward: it takes c's place
    assert hl.keys(hl.move(cells, "c", "a")) == ["c", "a", "b"]           # back
    assert hl.move(cells, "a", "c")[2] == {"w": "a", "size": "s"}         # sizes go with the widget
    assert cells == [{"w": "a", "size": "s"}, {"w": "b", "size": "m"}, {"w": "c", "size": "l"}]   # new lists
    assert hl.keys(hl.swap(cells, "a", "c")) == ["c", "b", "a"]
    assert hl.move(cells, "a", "a") == cells and hl.move(cells, "a", "zzz") == cells
    # Dropping onto a stacked widget joins the stack; leaving a stack of two leaves a widget.
    d = hl.default()
    joined = hl.move(d, "timetable_today", "needs_you")
    assert joined == [{"stack": ["ask", "needs_you", "timetable_today", "todos"], "size": "s"}]
    left = hl.move(d, "todos", "timetable_today")
    assert left == [{"w": "todos", "size": "s"}, {"w": "timetable_today", "size": "l"},
                    {"stack": ["ask", "needs_you"], "size": "s"}]


def test_step_resize_hide_add():
    d = hl.default()
    assert hl.keys(hl.step(d, "needs_you", -1)) == ["timetable_today", "needs_you", "ask", "todos"]   # within a stack
    out = hl.step(d, "ask", -1)                                           # off the top of a stack: out in front of it
    assert out == [{"w": "timetable_today", "size": "l"}, {"w": "ask", "size": "s"},
                   {"stack": ["needs_you", "todos"], "size": "s"}]
    assert hl.step(d, "timetable_today", -1) == d                         # already first
    assert hl.keys(hl.step(d, "timetable_today", 1)) == ["ask", "needs_you", "todos", "timetable_today"]
    assert hl.resize(d, "timetable_today", 1)[0]["size"] == "full"
    assert hl.resize(d, "timetable_today", 5)[0]["size"] == "full"       # no bigger than the page
    assert hl.resize(d, "todos", -1)[1]["size"] == "s"                    # a stack resizes as one
    assert hl.resize(d, "todos", 1)[1]["size"] == "m"
    hidden = hl.hide(hl.hide(d, "ask"), "needs_you")
    assert hidden == [{"w": "timetable_today", "size": "l"}, {"w": "todos", "size": "s"}]
    assert hl.hide(hl.hide(hidden, "todos"), "timetable_today") == []
    assert hl.add(hidden, "habits", "m")[-1] == {"w": "habits", "size": "m"}   # added at the end
    assert hl.add(hidden, "todos", "m") == hidden                          # already there


def test_reset_restores_the_default():
    assert hl.reset() == hl.default()
    assert hl.reset() is not hl.reset()


def test_unavailable_widgets_are_kept_when_saving():
    """A widget whose block is off right now keeps a place at the end, so it comes back when it's on again."""
    raw = [{"w": "focus", "size": "s"}, {"w": "todos", "size": "s"}, {"stack": ["ask", "needs_you"], "size": "s"}]
    available = {k: v for k, v in ALL.items() if k not in ("focus", "ask")}
    shown = hl.normalise(raw, available)
    new = hl.hide(shown, "todos")
    assert hl.keep_unavailable(raw, new, available) == [{"w": "needs_you", "size": "s"}, {"w": "focus", "size": "s"},
                                                         {"w": "ask", "size": "s"}]


# --- saving, with undo ---

def test_undo_reverts_a_move(blank_store):
    from venato import undo
    before = hl.default()
    blank_store.save_settings(home=before)
    undo.checkpoint_settings("Moved To-dos", home=hl.move(before, "todos", "timetable_today"))
    assert blank_store.load_settings()["home"][0] == {"w": "todos", "size": "s"}
    assert undo.pending() == "Moved To-dos"
    assert undo.restore() == "Moved To-dos"
    assert blank_store.load_settings()["home"] == before
    assert undo.pending() is None


def test_undo_settings_change_not_after_another_change(blank_store):
    from venato import undo
    undo.checkpoint_settings("Hid To-dos", home=[])
    assert blank_store.load_settings()["home"] == []
    blank_store.save_settings(home=hl.default())                          # changed again since
    assert undo.pending() is None and undo.restore() is None
    undo.checkpoint_settings("Hid Ask", home=[{"w": "todos", "size": "s"}])
    undo.restore()
    assert blank_store.load_settings()["home"] == hl.default()


# --- Home itself (AppTest) ---

def app():
    return AppTest.from_file(APP, default_timeout=60).run()


def has(at, key):
    return any(b.key == key for b in at.button)


def keys(at):
    out, todo = set(), [at.main]
    while todo:
        node = todo.pop()
        out.add(getattr(node, "key", None))
        todo += list(getattr(node, "children", {}).values())
    return out - {None}


def test_blank_install_renders_the_default(blank_store):
    at = app()
    assert not at.exception
    k = keys(at)
    assert {"hw_timetable_today", "hw_ask", "hw_needs_you", "hw_todos"} <= k
    assert not {"hw_deadlines", "hw_habits", "hw_focus"} & k
    assert any(m.value == "Nothing needs you. Go touch grass." for m in at.markdown)
    assert at.button(key="home_arrange")
    assert blank_store.load_settings()["first_seen"] == blank_store.local_today().isoformat()


def test_nothing_on_at_all_still_renders(blank_store):
    """No blocks, the assistant off: Home is just Needs you (the timetable and to-dos are gone with their blocks)."""
    blank_store.save_settings(blocks=[], blocks_optional=True, ai_enabled=False)
    at = app()
    assert not at.exception
    k = keys(at)
    assert "hw_needs_you" in k and not {"hw_timetable_today", "hw_ask", "hw_todos"} & k


def test_every_widget_hidden_shows_an_empty_state(blank_store):
    blank_store.save_settings(home=[])
    at = app()
    assert not at.exception
    assert not [x for x in keys(at) if x.startswith("hw_")]
    assert any("Home is empty" in m.value for m in at.markdown)
    assert at.button(key="home_add_needs_you")                            # + Add widget, straight away
    at.button(key="home_add_needs_you").click().run()
    assert not at.exception
    assert blank_store.load_settings()["home"] == [{"w": "needs_you", "size": "s"}]
    assert "hw_needs_you" in keys(at)


def test_arrange_mode(store):
    at = app()
    at.button(key="home_arrange").click().run()
    assert not at.exception
    assert at.button(key="home_done") and at.button(key="home_reset") and not has(at, "home_arrange")
    assert at.button(key="hwpick_todos") and at.button(key="hwbig_todos") and at.button(key="hwx_todos")
    assert "home_todos" in keys(at)                                       # real content while arranging
    assert at.button(key="hwl_timetable_today").disabled                  # already first
    # Tap to pick up, tap another to drop it there: saved straight away, with undo.
    at.button(key="hwpick_todos").click().run()
    assert at.session_state["home_picked"] == "todos"
    at.button(key="hwpick_timetable_today").click().run()
    saved = store.load_settings()["home"]
    assert hl.keys(saved)[:2] == ["todos", "timetable_today"] and at.session_state["home_picked"] is None
    assert at.button(key="undo_btn")
    at.button(key="hwbig_todos").click().run()                            # size +
    assert store.load_settings()["home"][0] == {"w": "todos", "size": "m"}
    at.button(key="hwr_todos").click().run()                              # → one step forward
    assert hl.keys(store.load_settings()["home"])[:2] == ["timetable_today", "todos"]
    at.button(key="hwx_ask").click().run()                                # ✕ hide
    assert "ask" not in hl.keys(store.load_settings()["home"]) and "hw_ask" not in keys(at)
    at.button(key="home_add_ask").click().run()                           # + Add widget: at the end
    assert hl.keys(store.load_settings()["home"])[-1] == "ask"
    at.button(key="undo_btn").click().run()                               # undo the add
    assert "ask" not in hl.keys(store.load_settings()["home"])
    at.button(key="home_reset").click().run()
    assert store.load_settings()["home"] == hl.default()
    at.button(key="home_done").click().run()
    assert not at.exception and at.button(key="home_arrange") and not has(at, "home_done")
    assert not [b for b in at.button if b.key and b.key.startswith("hwpick_")]


# --- Needs you ---

def test_needs_you_gathers(store, monkeypatch):
    from venato.ui import goal_time
    today = store.local_today()
    store.add_deadline("Essay", today + timedelta(days=3))
    store.add_deadline("Thesis", today + timedelta(days=30))              # not this week
    store.add_goal("Revision", "monthly", today, 200, "h", category_id="study")
    at = app()
    text = " ".join(m.value for m in at.markdown)
    assert "Essay" in text and "Thesis" not in text and "Revision" in text
    assert "Go touch grass" not in text
    # Phase 5's plans plug in here: a deadline with a plan on track doesn't need you.
    monkeypatch.setattr(goal_time, "deadline_needs_plan", lambda d, ctx: False)
    assert goal_time.needs_items()["deadlines"] == []


def test_block_needs_items(store, monkeypatch):
    from venato import blocks
    real = list(blocks.all_blocks())
    fake = blocks.Block(key="fake", name="Fake", icon=":material/star:", blurb="A test block",
                        needs=lambda: [{"text": "Feed the cat", "page": "Settings"}, "Water the plants"])
    monkeypatch.setattr(blocks, "all_blocks", lambda: [*real, fake])
    blocks.save(["fake"])
    at = app()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "Feed the cat" in text and "Water the plants" in text
    next(b for b in at.button if b.key and b.key.startswith("needs_open_")).click().run()
    assert at.sidebar.radio[0].value == "Settings"


def test_assistant_card_after_a_week(blank_store, monkeypatch):
    from venato.ui import goal_time
    blank_store.save_settings(ai_enabled=False)
    today = blank_store.local_today()
    at = app()                                                            # first use: recorded, no card yet
    assert blank_store.load_settings()["first_seen"] == today.isoformat()
    assert not goal_time.assistant_offer_due() and not has(at, "needs_ai_no")
    blank_store.save_settings(first_seen=(today - timedelta(days=6)).isoformat())
    assert not goal_time.assistant_offer_due()
    blank_store.save_settings(first_seen=(today - timedelta(days=7)).isoformat(),
                              eod_dismissed=[(today - timedelta(days=1)).isoformat(), today.isoformat()])
    assert goal_time.assistant_offer_due()
    at.run()
    assert any("Settings → Assistant" in m.value for m in at.markdown)
    assert not any("Go touch grass" in m.value for m in at.markdown)
    at.button(key="needs_ai_no").click().run()                            # dismissed: never again
    assert blank_store.load_settings()["assistant_offer_done"] is True
    assert not has(at, "needs_ai_no") and not goal_time.assistant_offer_due()
    assert any(m.value == "Nothing needs you. Go touch grass." for m in at.markdown)


def test_assistant_card_opens_settings_and_never_shows_when_on(blank_store):
    from venato.ui import goal_time
    week_ago = (blank_store.local_today() - timedelta(days=8)).isoformat()
    blank_store.save_settings(ai_enabled=True, first_seen=week_ago)
    assert not goal_time.assistant_offer_due()                            # already on
    blank_store.save_settings(ai_enabled=False)
    at = app()
    at.button(key="needs_ai_yes").click().run()
    assert not at.exception and at.sidebar.radio[0].value == "Settings"
    assert blank_store.load_settings()["assistant_offer_done"] is True


def test_existing_install_gets_first_seen_once(store):
    store.save_settings(first_seen="2026-01-01")
    app()
    assert store.load_settings()["first_seen"] == "2026-01-01"
    assert json.loads((store.DATA_DIR / "settings.json").read_text())["first_seen"] == "2026-01-01"


# --- fix round 1 ---

def test_repeats_inside_a_stack_and_across_cells_are_dropped():
    saved = [{"stack": ["ask", "ask", "todos"], "size": "s"}, {"w": "todos", "size": "m"},
             {"stack": ["ask", "habits", "habits"], "size": "m"}]
    assert hl.normalise(saved, ALL) == [{"stack": ["ask", "todos"], "size": "s"}, {"w": "habits", "size": "m"}]


def test_repeated_widget_renders(store):
    store.save_settings(home=[{"stack": ["ask", "ask", "todos"], "size": "s"}, {"w": "todos", "size": "m"}])
    at = app()
    assert not at.exception


def test_junk_list_gives_the_default_but_empty_stays_empty():
    assert hl.normalise(["junk"], ALL) == hl.default()
    assert hl.normalise([{"nonsense": 1}, 3], ALL) == hl.default()
    assert hl.normalise([], ALL) == []
    assert hl.normalise([{"w": "money", "size": "m"}], ALL) == []        # well formed, just not on offer


def test_picked_widget_gone_by_undo_isnt_still_picked(store):
    at = app()
    at.button(key="home_arrange").click().run()
    at.button(key="home_add_habits").click().run()
    at.button(key="hwpick_habits").click().run()
    assert any("picked up" in m.value for m in at.markdown)
    at.button(key="undo_btn").click().run()                               # Habits leaves Home
    assert not at.exception and "hw_habits" not in keys(at)
    assert not any("picked up" in m.value for m in at.markdown)


def test_arrows_off_only_when_they_would_do_nothing(store):
    at = app()
    at.button(key="home_arrange").click().run()
    assert at.button(key="hwl_timetable_today").disabled                  # first: nowhere to go
    assert not at.button(key="hwr_todos").disabled                        # last, but it can leave its stack
    at.button(key="hwr_todos").click().run()
    assert store.load_settings()["home"][-1] == {"w": "todos", "size": "s"}
    assert at.button(key="hwr_todos").disabled


def test_existing_install_without_first_seen(store):
    """An install from before this update (set up, with data, no first_seen): recorded on its first Home,
    and the assistant card a week after that."""
    from venato.ui import goal_time
    store.add_todo("Old to-do", "daily", store.local_today())
    store.save_settings(ai_enabled=False)
    assert "first_seen" not in store.load_settings()
    at = app()
    today = store.local_today()
    assert store.load_settings()["first_seen"] == today.isoformat()
    assert not goal_time.assistant_offer_due() and not has(at, "needs_ai_yes")
    assert goal_time.assistant_offer_due(today + timedelta(days=7))
    assert not goal_time.assistant_offer_due(today + timedelta(days=6))
