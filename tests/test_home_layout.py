"""Home's tile grid (venato/home_layout.py): the default, migrating old layouts, placing tiles, the edit
operations and undo; then Home itself (AppTest): a blank install, every tile hidden, Edit Home,
Needs you and its one-time assistant card."""

import json
from datetime import date, timedelta
from pathlib import Path

from streamlit.testing.v1 import AppTest

from venato import home_layout as hl
import fragment_run

APP = str(Path(__file__).resolve().parents[1] / "app.py")

# What a full install offers: every tile key with its default size.
ALL = {"timetable_today": "large", "ask": "wide", "needs_you": "wide", "todos": "wide", "deadlines": "small",
       "goals": "wide", "habits": "small", "journal": "small", "focus": "small", "modules": "small", "review": "small"}

# The layout every install had before tiles: a timetable ⅔ wide, then a stack, in the 12-column sizes.
OLD_DEFAULT = [{"w": "timetable_today", "size": "l"}, {"stack": ["ask", "needs_you", "todos"], "size": "s"}]


# --- the layout itself (pure) ---

def test_default_layout():
    d = hl.default()
    assert hl.keys(d) == ["timetable_today", "todos", "goals", "focus", "modules", "habits", "review", "needs_you"]
    assert d[0] == {"w": "timetable_today", "size": "large"}
    assert hl.normalise(None, ALL) == d                                  # no saved key: the default
    assert hl.normalise("rubbish", ALL) == d
    assert hl.hidden(d, ALL) == ["ask", "deadlines", "journal"]           # the rest wait in "Add a tile"
    assert hl.reset() == d and hl.reset() is not hl.reset()


def test_old_default_migrates():
    """Old 12-column sizes become tile sizes and stacks are flattened, in order; nothing is lost."""
    assert hl.normalise(OLD_DEFAULT, ALL) == [{"w": "timetable_today", "size": "large"}, {"w": "ask", "size": "small"},
                                              {"w": "needs_you", "size": "small"}, {"w": "todos", "size": "small"}]
    old = [{"w": "goals", "size": "m"}, {"w": "habits", "size": "full"}, {"w": "focus", "size": "s"}]
    assert hl.normalise(old, ALL) == [{"w": "goals", "size": "wide"}, {"w": "habits", "size": "wide"},
                                      {"w": "focus", "size": "small"}]


def test_sizes_a_tile_doesnt_come_in_fall_back():
    sizes = {"focus": ("small", "wide"), "timetable_today": ("wide", "large", "tall")}
    saved = [{"w": "focus", "size": "large"}, {"w": "timetable_today", "size": "s"}, {"w": "todos", "size": "huge"}]
    assert hl.normalise(saved, ALL, sizes) == [{"w": "focus", "size": "small"},            # its default
                                               {"w": "timetable_today", "size": "large"},
                                               {"w": "todos", "size": "wide"}]


def test_unknown_disabled_and_repeated_tiles_skipped():
    saved = [{"w": "money", "size": "m"}, {"w": "todos", "size": "small"}, {"w": "todos", "size": "large"},
             {"stack": ["ask", "gone", "needs_you", "needs_you"], "size": "s"}, {"nonsense": 1}, "todos"]
    available = {k: v for k, v in ALL.items() if k != "ask"}              # e.g. the assistant is off
    assert hl.normalise(saved, available) == [{"w": "todos", "size": "small"}, {"w": "needs_you", "size": "small"}]


def test_junk_list_gives_the_default_but_empty_stays_empty():
    assert hl.normalise(["junk"], ALL) == hl.default()
    assert hl.normalise([{"nonsense": 1}, 3], ALL) == hl.default()
    assert hl.normalise([], ALL) == []
    assert hl.normalise([{"w": "money", "size": "m"}], ALL) == []        # well formed, just not on offer


def test_place_fills_gaps():
    """Each tile takes the first place it fits, left to right, top to bottom (like the browser's dense grid)."""
    assert hl.place(hl.default()) == [(0, 0), (0, 2), (1, 2), (2, 0), (2, 1), (2, 2), (2, 3), (3, 0)]
    cells = [{"w": "a", "size": "wide"}, {"w": "b", "size": "large"}, {"w": "c", "size": "small"},
             {"w": "d", "size": "small"}, {"w": "e", "size": "tall"}, {"w": "f", "size": "small"}]
    assert hl.place(cells) == [(0, 0), (0, 2), (1, 0), (1, 1), (2, 0), (2, 1)]
    assert hl.place([{"w": "a", "size": "large"}], columns=1) == [(0, 0)]   # never wider than the grid


def test_move_step_resize_hide_add():
    cells = [{"w": "a", "size": "small"}, {"w": "b", "size": "wide"}, {"w": "c", "size": "large"}]
    assert hl.keys(hl.move(cells, "a", "c")) == ["b", "c", "a"]           # forward: lands after c
    assert hl.keys(hl.move(cells, "c", "a")) == ["c", "a", "b"]           # back: lands before a
    assert hl.keys(hl.move(cells, "a", None)) == ["b", "c", "a"]          # to the end
    assert hl.move(cells, "a", "c")[2] == {"w": "a", "size": "small"}     # its size goes with it
    assert hl.move(cells, "a", "a") == cells and hl.move(cells, "a", "zzz") == cells
    assert hl.keys(hl.step(cells, "b", -1)) == ["b", "a", "c"] and hl.step(cells, "a", -1) == cells
    assert hl.resize(cells, "a", "tall")[0] == {"w": "a", "size": "tall"}
    assert hl.resize(cells, "a", "huge") == cells                         # only the four sizes
    assert hl.keys(hl.hide(cells, "b")) == ["a", "c"]
    assert hl.add(cells, "d", "s")[-1] == {"w": "d", "size": "small"} and hl.add(cells, "a") == cells
    assert cells == [{"w": "a", "size": "small"}, {"w": "b", "size": "wide"}, {"w": "c", "size": "large"}]   # new lists


def test_unavailable_tiles_are_kept_when_saving():
    """A tile whose block is off right now keeps a place at the end, so it comes back when it's on again."""
    raw = [{"w": "focus", "size": "small"}, {"w": "todos", "size": "small"}, {"stack": ["ask", "needs_you"], "size": "s"}]
    available = {k: v for k, v in ALL.items() if k not in ("focus", "ask")}
    new = hl.hide(hl.normalise(raw, available), "todos")
    assert hl.keep_unavailable(raw, new, available) == [{"w": "needs_you", "size": "small"},
                                                         {"w": "focus", "size": "small"}, {"w": "ask", "size": "small"}]


# --- saving, with undo ---

def test_undo_reverts_a_move(blank_store):
    from venato import undo
    before = hl.default()
    blank_store.save_settings(home=before)
    undo.checkpoint_settings("Moved To-dos", home=hl.move(before, "todos", "timetable_today"))
    assert blank_store.load_settings()["home"][0] == {"w": "todos", "size": "wide"}
    assert undo.pending() == "Moved To-dos"
    assert undo.restore() == "Moved To-dos"
    assert blank_store.load_settings()["home"] == before
    assert undo.pending() is None


def test_undo_settings_change_not_after_another_change(blank_store):
    from venato import undo
    undo.checkpoint_settings("Removed To-dos", home=[])
    assert blank_store.load_settings()["home"] == []
    blank_store.save_settings(home=hl.default())                          # changed again since
    assert undo.pending() is None and undo.restore() is None
    undo.checkpoint_settings("Removed Ask", home=[{"w": "todos", "size": "small"}])
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


def saved(store):
    return store.load_settings()["home"]


def test_blank_install_renders_the_default(blank_store):
    at = app()
    assert not at.exception
    k = keys(at)
    assert {"hw_timetable_today", "hw_todos", "hw_goals", "hw_needs_you", "home_grid"} <= k
    assert not {"hw_deadlines", "hw_journal", "hw_ask"} & k
    assert any(m.value == "Nothing needs you. Go touch grass." for m in at.markdown)
    assert at.button(key="home_arrange").label == "Edit Home"
    assert at.button(key="home_settings")                                 # the gear
    assert blank_store.load_settings()["first_seen"] == blank_store.local_today().isoformat()


def test_grid_spans_follow_sizes(store):
    store.save_settings(home=[{"w": "timetable_today", "size": "large"}, {"w": "focus", "size": "small"},
                              {"w": "todos", "size": "tall"}, {"w": "goals", "size": "wide"}])
    css = " ".join(h.proto.body for h in app().get("html"))
    for k, span in (("timetable_today", "span 2; grid-row: span 2"), ("focus", "span 1; grid-row: span 1"),
                    ("todos", "span 1; grid-row: span 2"), ("goals", "span 2; grid-row: span 1")):
        assert f".st-key-home_grid > div:has(> .st-key-hw_{k}) {{ grid-column: {span}; }}" in css


def test_old_layout_migrates_on_home(store):
    store.save_settings(home=OLD_DEFAULT, ai_enabled=True)
    at = app()
    assert not at.exception
    assert {"hw_timetable_today", "hw_ask", "hw_needs_you", "hw_todos"} <= keys(at)
    assert saved(store) == OLD_DEFAULT                                    # only read, until the next change
    at.button(key="home_arrange").click().run()
    at.button(key="hwx_ask").click().run()
    assert saved(store) == [{"w": "timetable_today", "size": "large"},
                            {"w": "needs_you", "size": "wide"},               # it doesn't come in small
                            {"w": "todos", "size": "small"}]


def test_nothing_on_at_all_still_renders(blank_store):
    """No blocks, the assistant off: Home is just Needs you (the other tiles are gone with their blocks)."""
    blank_store.save_settings(blocks=[], blocks_optional=True, ai_enabled=False)
    at = app()
    assert not at.exception
    k = keys(at)
    assert "hw_needs_you" in k and not {"hw_timetable_today", "hw_ask", "hw_todos"} & k


def test_every_tile_hidden_shows_the_gear_and_add_a_tile(blank_store):
    blank_store.save_settings(home=[])
    at = app()
    assert not at.exception
    assert not [x for x in keys(at) if x.startswith("hw_")]
    assert any("Home is empty" in m.value for m in at.markdown)
    assert at.button(key="home_settings")                                 # you can't remove your way out
    at.button(key="home_add_prompt").click().run()                        # "Add a tile": into Edit Home
    assert at.session_state["home_arranging"] is True
    at.button(key="home_add_needs_you").click().run()
    assert not at.exception
    assert saved(blank_store) == [{"w": "needs_you", "size": "wide"}]
    assert "hw_needs_you" in keys(at)
    at.button(key="home_settings").click().run()
    assert at.session_state["page"] == "Settings"


def test_edit_home(store):
    at = app()
    at.button(key="home_arrange").click().run()
    assert not at.exception
    assert at.title[0].value == "Edit Home"
    assert at.button(key="home_done") and at.button(key="home_reset") and not has(at, "home_arrange")
    assert at.button(key="hwpick_todos") and at.button(key="hwx_todos") and not has(at, "go_tile_todos")
    assert "home_todos" in keys(at) and "home_add_panel" in keys(at)      # real content, and "Add a tile"
    assert has(at, "home_add_deadlines") and not has(at, "home_add_todos")  # only hidden tiles are offered
    assert not has(at, "hwsz_todos_small")                                # sizes only on the picked-up tile
    # Tap to pick up: highlighted, with sizes, ← / → and a drop slot.
    at.button(key="hwpick_todos").click().run()
    assert at.session_state["home_picked"] == "todos"
    assert {"hwsz_todos_small", "hwsz_todos_wide", "hwsz_todos_large", "hwsz_todos_tall", "hwl_todos", "hwr_todos",
            "home_drop_end"} <= {b.key for b in at.button}
    assert [b.key for b in at.button if b.key.startswith("hwsz_focus")] == []
    at.button(key="hwsz_todos_large").click().run()                       # resize to a named size
    assert saved(store)[1] == {"w": "todos", "size": "large"}
    at.button(key="hwpick_timetable_today").click().run()                 # tap another: moved there
    assert hl.keys(saved(store))[:2] == ["todos", "timetable_today"] and at.session_state["home_picked"] is None
    assert at.button(key="undo_btn")
    at.button(key="hwpick_todos").click().run()
    at.button(key="home_drop_end").click().run()                          # Drop here: to the end
    assert hl.keys(saved(store))[-1] == "todos"
    at.button(key="hwx_focus").click().run()                              # − remove
    assert "focus" not in hl.keys(saved(store)) and "hw_focus" not in keys(at)
    at.button(key="home_add_focus").click().run()                         # + Add: at the end, its own size
    assert saved(store)[-1] == {"w": "focus", "size": "small"}
    at.button(key="undo_btn").click().run()                               # undo the add
    assert "focus" not in hl.keys(saved(store))
    at.button(key="home_reset").click().run()
    assert saved(store) == hl.default()
    at.button(key="home_done").click().run()
    assert not at.exception and at.button(key="home_arrange") and not has(at, "home_done")
    assert not [b for b in at.button if b.key and b.key.startswith("hwpick_")]


def test_drag_onto_another_tile_moves_it(store):
    at = app()
    at.button(key="home_arrange").click().run()
    fragment_run.trigger(at, "home_flip", "drop", {"from": "review", "to": "timetable_today", "nonce": "x"})
    assert not at.exception
    assert hl.keys(saved(store))[:2] == ["review", "timetable_today"]


def test_tile_supported_sizes_only(store):
    at = app()
    at.button(key="home_arrange").click().run()
    at.button(key="hwpick_focus").click().run()
    assert sorted(b.key for b in at.button if b.key.startswith("hwsz_focus")) == ["hwsz_focus_small", "hwsz_focus_wide"]


def test_picked_tile_gone_by_undo_isnt_still_picked(store):
    at = app()
    at.button(key="home_arrange").click().run()
    at.button(key="home_add_journal").click().run()
    at.button(key="hwpick_journal").click().run()
    assert any("picked up" in m.value for m in at.caption)
    at.button(key="undo_btn").click().run()                               # Journal leaves Home
    assert not at.exception and "hw_journal" not in keys(at)
    assert not any("picked up" in m.value for m in at.caption)


def test_arrows_off_only_when_they_would_do_nothing(store):
    at = app()
    at.button(key="home_arrange").click().run()
    at.button(key="hwpick_timetable_today").click().run()
    assert at.button(key="hwl_timetable_today").disabled                  # first: nowhere to go
    at.button(key="hwr_timetable_today").click().run()
    assert hl.keys(saved(store))[:2] == ["todos", "timetable_today"]
    at.button(key="hwpick_timetable_today").click().run()                 # put it back down
    at.button(key="hwpick_needs_you").click().run()
    assert at.button(key="hwr_needs_you").disabled                        # last


def test_esc_leaves_edit_home(store):
    at = app()
    at.button(key="home_arrange").click().run()
    fragment_run.trigger(at, "venato_nav", "go", {"slug": "", "esc": True, "nonce": "x"})
    assert not at.exception and at.session_state["home_arranging"] is False and at.session_state["page"] == "Home"


def test_repeated_tile_renders(store):
    store.save_settings(home=[{"stack": ["todos", "todos"], "size": "s"}, {"w": "todos", "size": "m"}])
    at = app()
    assert not at.exception


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
    assert at.session_state["page"] == "Settings"


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
    assert not at.exception and at.session_state["page"] == "Settings"
    assert blank_store.load_settings()["assistant_offer_done"] is True


def test_existing_install_gets_first_seen_once(store):
    store.save_settings(first_seen="2026-01-01")
    app()
    assert store.load_settings()["first_seen"] == "2026-01-01"
    assert json.loads((store.DATA_DIR / "settings.json").read_text())["first_seen"] == "2026-01-01"


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
