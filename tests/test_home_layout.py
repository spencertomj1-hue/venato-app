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
ALL = {"timetable_today": "column", "ask": "wide", "needs_you": "wide", "todos": "wide", "deadlines": "small",
       "goals": "wide", "habits": "small", "journal": "small", "focus": "small", "modules": "small", "review": "small"}

# The layout every install had before tiles: a timetable ⅔ wide, then a stack, in the 12-column sizes.
OLD_DEFAULT = [{"w": "timetable_today", "size": "l"}, {"stack": ["ask", "needs_you", "todos"], "size": "s"}]


# --- the layout itself (pure) ---

def test_default_layout():
    d = hl.default()
    assert hl.keys(d) == ["timetable_today", "todos", "focus", "goals", "review", "habits", "needs_you", "modules"]
    assert d[0] == {"w": "timetable_today", "size": "column"}        # the whole day, down the left
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
    sizes = {"focus": ("small", "wide"), "timetable_today": ("wide", "large", "tall", "column")}
    saved = [{"w": "focus", "size": "large"}, {"w": "timetable_today", "size": "s"}, {"w": "todos", "size": "huge"}]
    assert hl.normalise(saved, ALL, sizes) == [{"w": "focus", "size": "small"},            # its default
                                               {"w": "timetable_today", "size": "column"},  # its default
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


def test_default_fits_three_rows():
    """The starting Home is three rows (Home sizes its rows from the window, so it fits one screen). A student's
    Modules tile starts a fourth: the rows share the screen four ways rather than a tile being left off."""
    no_modules = {k: v for k, v in ALL.items() if k != "modules"}
    assert hl.rows(hl.normalise(None, no_modules)) == 3
    assert hl.rows(hl.default()) == 4
    assert hl.span("column") == (1, 3) and hl.SIZE_NAMES["column"] == "Column"
    assert hl.rows([{"w": "a", "size": "column"}]) == 3
    assert hl.rows([]) == 0
    assert hl.rows([{"w": "a", "size": "large"}, {"w": "b", "size": "wide"}, {"w": "c", "size": "small"}]) == 2
    assert hl.rows([{"w": "a", "size": "large"}, {"w": "b", "size": "wide"}, {"w": "c", "size": "tall"}]) == 3


def test_an_old_saved_layout_still_normalises():
    """A layout saved before this Home (the old default: a Large timetable first, in the 12-column sizes or
    the tile sizes) keeps its own sizes: the new default is only for installs that never saved one, and Reset."""
    before = [{"w": "timetable_today", "size": "large"}, {"w": "todos", "size": "wide"}, {"w": "goals", "size": "wide"},
              {"w": "focus", "size": "small"}, {"w": "modules", "size": "small"}, {"w": "habits", "size": "small"},
              {"w": "review", "size": "small"}, {"w": "needs_you", "size": "wide"}]
    assert hl.normalise(before, ALL) == before
    tall = [{"w": "timetable_today", "size": "tall"}]                  # saved before Column: stays Tall
    assert hl.normalise(tall, ALL, {"timetable_today": ("wide", "large", "tall", "column")}) == tall
    sizes = {"todos": ("small", "wide"), "timetable_today": ("wide", "large", "tall")}
    assert hl.normalise([{"w": "todos", "size": "large"}, {"w": "timetable_today", "size": "l"}], ALL, sizes) == \
        [{"w": "todos", "size": "wide"}, {"w": "timetable_today", "size": "large"}]   # To-dos no longer comes Large


def test_place_fills_gaps():
    """Each tile takes the first place it fits, left to right, top to bottom (like the browser's dense grid)."""
    assert hl.place(hl.default()) == [(0, 0), (0, 1), (0, 3), (1, 1), (1, 3), (2, 1), (2, 2), (3, 0)]
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
                              {"w": "needs_you", "size": "tall"}, {"w": "goals", "size": "wide"}])
    css = " ".join(h.proto.body for h in app().get("html"))
    for k, span in (("timetable_today", "span 2; grid-row: span 2"), ("focus", "span 1; grid-row: span 1"),
                    ("needs_you", "span 1; grid-row: span 2"), ("goals", "span 2; grid-row: span 1")):
        assert f".st-key-home_grid > div:has(> .st-key-hw_{k}) {{ grid-column: {span}; }}" in css
    # The rows share the window's height: as many as the layout uses (goals drops to a third row), tiles clip.
    assert "grid-template-rows: repeat(3, var(--home-row))" in css and "var(--home-grid-h" in css
    assert '[class*="st-key-hw_"] { overflow: hidden; }' in css


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
    assert at.button(key="hwx_todos") and at.button(key="hwsz_todos") and not has(at, "go_tile_todos")
    assert not [b for b in at.button if b.key and b.key.startswith(("hwpick_", "hwl_", "hwr_", "home_drop"))]
    assert "home_todos" in keys(at) and "home_add_panel" in keys(at)      # real content, and "Add a tile"
    assert has(at, "home_add_deadlines") and not has(at, "home_add_todos")  # only hidden tiles are offered
    at.button(key="hwsz_todos").click().run()                             # size steps on: Wide -> Small
    assert saved(store)[1] == {"w": "todos", "size": "small"}
    at.button(key="hwsz_todos").click().run()                             # and round again
    assert saved(store)[1] == {"w": "todos", "size": "wide"}
    at.button(key="hwx_focus").click().run()                              # − remove
    assert "focus" not in hl.keys(saved(store)) and "hw_focus" not in keys(at)
    at.button(key="home_add_focus").click().run()                         # + Add: at the end, its own size
    assert saved(store)[-1] == {"w": "focus", "size": "small"}
    at.button(key="home_reset").click().run()
    assert saved(store) == hl.default()
    at.button(key="home_done").click().run()
    assert not at.exception and at.button(key="home_arrange") and not has(at, "home_done")


def test_home_edits_are_quiet_but_undoable(store):
    from venato import undo
    before = store.load_settings().get("home")
    at = app()
    at.button(key="home_arrange").click().run()
    at.button(key="hwx_focus").click().run()
    assert undo.pending() and undo.is_quiet()                             # no bar, but Cmd/Ctrl+Z still has it
    assert undo.restore() and store.load_settings().get("home") == before


def test_drag_saves_the_order_it_was_dropped_in(store):
    at = app()
    at.button(key="home_arrange").click().run()
    order = hl.keys(hl.default())
    order.insert(0, order.pop(order.index("review")))
    fragment_run.trigger(at, "home_flip", "drop", {"order": order, "nonce": "x"})
    assert not at.exception
    assert hl.keys(saved(store)) == order
    assert saved(store)[0] == {"w": "review", "size": "small"}           # its size goes with it


def test_reorder():
    cells = [{"w": "a", "size": "small"}, {"w": "b", "size": "wide"}, {"w": "c", "size": "large"}]
    assert hl.keys(hl.reorder(cells, ["c", "a", "b"])) == ["c", "a", "b"]
    assert hl.keys(hl.reorder(cells, ["c", "zzz"])) == ["c", "a", "b"]    # unknown ignored, left-out keep order
    assert hl.reorder(cells, ["b", "a", "c"])[0] == {"w": "b", "size": "wide"}


def test_size_button_only_when_there_is_a_choice(store):
    at = app()
    at.button(key="home_arrange").click().run()
    assert has(at, "hwsz_focus")
    at.button(key="hwsz_focus").click().run()
    assert {"w": "focus", "size": "wide"} in saved(store)                 # Focus: Small or Wide


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


# --- Tiles show a summary (Home fits one screen); the rest is a tap away ---

def test_todos_tile_shows_three(store):
    """The To-dos tile: at most 3 to-dos a list, then "+N more" (drawn by the component from `limit`)."""
    today = store.local_today()
    for i in range(9):
        store.add_todo(f"Task {i}", "daily", today)
    at = app()
    data = fragment_run.component_data(at, "home_todos")
    assert data["tile"] and [s["limit"] for s in data["sections"]] == [3, 3, 3]
    assert len(data["sections"][0]["goals"]) == 9                         # all sent: the count and "+6 more"


def test_goals_tile_top_three_behind_first(store):
    """The Goals tile: the top 3 goals, ones behind first, each a name and a bar on one line; "and N more"."""
    from venato.ui import goals
    today = store.local_today()
    for name in ("Books", "Films"):                                       # done: on track, listed first
        store.add_goal(name, "yearly", today, 1, name.lower())
        store.set_goal_progress(next(g["id"] for g in store.goals_in("yearly", today) if g["title"] == name), 1)
    for name in ("Essays", "Sketches"):                                   # ten days in, nothing done: behind
        store.add_goal(name, None, today - timedelta(days=10), 10, name.lower(), due=today + timedelta(days=10))
    order = [(g["title"], p["state"]) for g, p in goals.home_goals()]
    assert [t for t, _ in order[:2]] == ["Essays", "Sketches"] and {s for _, s in order[:2]} == {"behind"}
    store.save_settings(home=[{"w": "goals", "size": "wide"}])
    html = " ".join(h.proto.body for h in app().get("html"))
    assert html.count('class="hg-row"') == 3 and "and 1 more" in html
    assert html.index(">Essays<") < html.index(">Sketches<") < html.index(">Books<")
    assert "hg-line" not in html.split("hg-rows", 1)[1]                    # no second line of text


def test_needs_you_tile_shows_three_then_more(store):
    """Needs you: the first 3 things, the last sharing its line with "+N more"; a tap on the tile opens a dialog
    with all of them (and their buttons, under their own keys)."""
    today = store.local_today()
    for i in range(5):
        store.add_deadline(f"Deadline {i}", today + timedelta(days=i + 1))
    store.save_settings(home=[{"w": "needs_you", "size": "wide"}])
    at = app()
    assert not at.exception
    shown = [m.value for m in at.markdown if "Deadline" in m.value]
    assert len(shown) == 3 and any(c.value == "+2 more" for c in at.caption)
    at.button(key="open_tile_needs_you").click().run()
    assert not at.exception
    assert len([m.value for m in at.markdown if "Deadline" in m.value]) == 3 + 5   # the tile, and the dialog
