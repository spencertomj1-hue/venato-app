# Modules Glue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the module the reliable glue between the uni timetable, Canvas, deadlines and study hours for the whole term, not just at setup.

**Architecture:** Detection and linking move out of `ui/onboarding.py` into `venato/blocks/grades.py` so they run on every feed sync and are offered through Home's "Needs you". Linking lectures to modules gets a per-module title rule and per-series overrides, on top of the existing code match. A Links panel on each module's page, plus an Unfiled list, lets a student fix any link. Module codes resolve to the module's category everywhere a category is typed (focus, log), and each card shows what's linked.

**Tech Stack:** Python 3.13, Streamlit, SQLite (`store.db()`), pytest.

**Spec:** The "1-5" list in this session's chat: (1) detect new modules and Canvas courses after setup, (2) match lectures without a code, (3) fix links after setup, (4) the module as a tag across the app, (5) show the links on each card.

## Global Constraints

- `venato/store/` has no Streamlit imports and never imports `venato.blocks`. Read `gr_modules` there with SQL only, and treat a missing table (`sqlite3.OperationalError`) as "no modules".
- Never rewrite existing data in a migration (HANDOVER: "existing data isn't rewritten"). New columns default to NULL.
- A link the student set by hand always beats an automatic one (same rule as `link_canvas_course` and deadlines).
- UI copy is short, plain British English, no jargon ("Unfiled", "Links", not "mapping").
- Restart the app after changes: Streamlit only hot-reloads `app.py`.
- Run the tests with `pytest -q` from the repo root.

## Review Focus

1. **A new term's feed whose old modules are still in Venato:** only codes and courses that aren't already in Venato and haven't been dismissed are offered. Test in Task 1.
2. **A title rule that's too broad** (e.g. "Lab" matching every lab): code match and per-series overrides win over title rules, and the first module by `created_at` wins between rules. Test in Task 2.
3. **Re-sync after a manual override:** `replace_outlook` deletes and re-inserts every row, so the overrides must live in their own table, keyed by normalised title, not on `tt_outlook`. Test in Task 2.
4. **Deleting a module that has overrides or a dismissal:** its override rows go, and its series show up as Unfiled again. Test in Task 3.
5. **A module code typed in lower case or with a space ("chem 50001")** in focus: `feeds.norm_code` normalises both sides. Test in Task 4.

---

### Task 1: Detect new modules and Canvas courses after setup

**Files:**
- Modify: `venato/blocks/grades.py` (new "Detection" section; `BLOCK` gains `needs=_needs`)
- Modify: `venato/ui/onboarding.py:140-180` (`detected_modules` and `canvas_courses` call the new functions, keeping their `ob` caching)
- Modify: `venato/ui/grades.py` (`render_page`: a "New in your calendars" card above the stats when `gr.new_found()` has anything)
- Test: `tests/test_grades.py`

**Interfaces:**
- Produces:
  - `gr.detected(day=None) -> list[dict]`: `[{code, name, count}]` from `outlook.cached_calendars()` (non-Canvas feeds, through `feeds.detect_modules`). This is the body moved out of `onboarding.detected_modules`, minus the `ob` cache.
  - `gr.detected_courses(day=None) -> list[dict]`: `[{course_id, label, titles, module_id}]`, moved out of `onboarding.canvas_courses`, minus the cache.
  - `gr.new_found(day=None) -> {"modules": [...], "courses": [...]}`: detected modules with no matching module (same code via `feeds.norm_code`, else same name, case-insensitive) and not dismissed, plus courses with `module_id is None` and not dismissed.
  - `gr.dismiss(kind: str, key: str) -> None`: kind is `"module"` (key = code, or lowercased name when there's no code) or `"course"` (key = course_id). Saved in settings.json as `modules_dismissed: {"module": [...], "course": [...]}`.
  - `gr._module_for(code, name)` moves here from onboarding (onboarding imports it).

- [ ] **Step 1: Write the failing tests**

```python
def test_new_found_offers_only_unknown_and_undismissed(gr, store, ol):
    ol.save_url(OUTLOOK_URL)
    ol._save_extra([{"id": "c1", "name": "Canvas", "url": CANVAS_URL}])
    ol.sync(date(2026, 11, 20), fetcher={OUTLOOK_URL: UNI, CANVAS_URL: CANVAS}.__getitem__)
    gr.add_module("Organic Chemistry", code="CHEM50001")
    found = gr.new_found(date(2026, 11, 20))
    codes = {m["code"] for m in found["modules"]}
    assert "CHEM50001" not in codes and "CHEM60004" in codes
    gr.dismiss("module", "CHEM60004")
    assert "CHEM60004" not in {m["code"] for m in gr.new_found(date(2026, 11, 20))["modules"]}
    course = found["courses"][0]["course_id"]
    gr.dismiss("course", course)
    assert course not in {c["course_id"] for c in gr.new_found(date(2026, 11, 20))["courses"]}

def test_needs_you_mentions_new_modules(gr, store, ol):
    # same sync as above, no modules added
    items = [i["text"] for i in blocks.needs() if i["block"] == "grades"]
    assert any("new module" in t for t in items)
```

- [ ] **Step 2: Run them to check they fail**

Run: `pytest tests/test_grades.py -k "new_found or needs_you" -q`
Expected: FAIL with `AttributeError: ... has no attribute 'new_found'`

- [ ] **Step 3: Implement `detected`, `detected_courses`, `new_found`, `dismiss` and `_needs` in `venato/blocks/grades.py`; point onboarding at them**

`_needs()` returns at most one item: `{"text": "N new modules in your timetable" (plus " · M Canvas courses to link" when there are any), "icon": ":material/school:", "page": "grades"}`, or `[]`. Make sure `tests/test_setup.py` still passes after the onboarding change.

- [ ] **Step 4: Add the "New in your calendars" card to `render_page`**

Each new module gets **Add** (`gr.add_module(name, onboarding.DEFAULT_CREDITS, code=code)`) and **Ignore** (`gr.dismiss`). Each course gets a module selectbox (`gr.link_canvas_course`) and **Ignore**. Show its `titles` so the student can recognise it.

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_grades.py tests/test_setup.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add venato/blocks/grades.py venato/ui/onboarding.py venato/ui/grades.py tests/test_grades.py
git commit -m "Modules: offer new modules and Canvas courses after every sync"
```

---

### Task 2: Match lectures with no code (title rules and per-series overrides)

**Files:**
- Modify: `venato/blocks/grades.py` (`SCHEMA`: new table; `_migrate`: new column; `add_module` and `update_module` accept `match`)
- Modify: `venato/store/outlook.py:32-42` (`_tag_modules` becomes Python, not one UPDATE)
- Modify: `venato/feeds.py` (export `strip_kind = _strip_kind`)
- Test: `tests/test_grades.py`

**Interfaces:**
- Produces:
  - Column `gr_modules.match TEXT`: words that a lecture title must contain (case-insensitive). NULL means use the module's name when it has no code.
  - Table `gr_event_links (title_key TEXT PRIMARY KEY, module_id TEXT)`: `module_id` NULL means "not a module".
  - `store.title_key(title: str) -> str`: `feeds.strip_kind(title).lower()` with whitespace collapsed.
  - `_tag_modules(conn)` priority for each event, first that matches:
    1. an override row for its `title_key`
    2. the code match (as now)
    3. a module whose `match`, or whose name if it has no code and no `match`, is contained in `title_key`, earliest `created_at` first
  - `M_COLS` gains `"match"`.

- [ ] **Step 1: Write the failing tests**

```python
def test_module_without_code_gets_its_lectures_by_name(gr, store, ol):
    # UNI's "Spectroscopy" events have no code that matches a module
    sync_uni(ol)                                   # helper: save_url + sync on UNI
    spec = gr.add_module("Spectroscopy")
    assert all(e["module_id"] == spec for e in events_titled(store, "Spectroscopy"))

def test_match_rule_and_override_priority(gr, store, ol):
    sync_uni(ol)
    org = gr.add_module("Organic Chemistry", code="CHEM50001")
    other = gr.add_module("Other", match="organic")          # broad rule loses to the code
    assert all(e["module_id"] == org for e in events_titled(store, "Organic Chemistry"))
    gr.file_series("Summer project chat", other)             # Task 3's function, defined here
    sync_uni(ol)                                             # survives a re-sync
    assert all(e["module_id"] == other for e in events_titled(store, "Summer project chat"))
    gr.file_series("Organic Chemistry", None)                # "not a module" beats the code
    assert not any(e["module_id"] for e in events_titled(store, "Organic Chemistry"))
```

- [ ] **Step 2: Run them to check they fail**

Run: `pytest tests/test_grades.py -k "without_code or priority" -q`
Expected: FAIL

- [ ] **Step 3: Add the column, the table, `match` on `add_module` / `update_module`, and `gr.file_series(title: str, module_id: str | None) -> None`**

`file_series` upserts `gr_event_links` and calls `store.tag_outlook_modules()`. `update_module` re-tags whenever `code` or `match` changes.

- [ ] **Step 4: Rewrite `_tag_modules(conn)` in Python using the priority above**

Read `uid, title, module_code` from `tt_outlook`, then modules and overrides (wrap the `gr_*` reads in `try/except sqlite3.OperationalError`), and `executemany` the `module_id`s. Compute it once per title, not per row.

- [ ] **Step 5: Run the whole grades and outlook suites**

Run: `pytest tests/test_grades.py tests/test_outlook.py -q`
Expected: PASS (the existing `test_sync_sends_canvas_...` must still pass: "Spectroscopy" stays untagged there because no module of that name exists)

- [ ] **Step 6: Commit**

```bash
git add venato/blocks/grades.py venato/store/outlook.py venato/feeds.py tests/test_grades.py
git commit -m "Modules: lectures match by title rule and per-series overrides, not just code"
```

---

### Task 3: Fix links after setup (Links panel and Unfiled list)

**Files:**
- Modify: `venato/blocks/grades.py` (`unfiled_series`, `unfiled_deadlines`; `delete_module` clears its `gr_event_links` rows)
- Modify: `venato/ui/module_page.py` (a "Links" expander above "Module settings")
- Modify: `venato/ui/grades.py` (an "Unfiled" card on the Modules page, shown only when non-empty)
- Test: `tests/test_grades.py`

**Interfaces:**
- Consumes: `gr.file_series`, `gr.update_module(mid, code=..., match=...)`, `gr.link_canvas_course`, `gr.detected_courses` (Tasks 1-2).
- Produces:
  - `gr.unfiled_series(today: date, weeks: int = 8) -> list[dict]`: `[{title, count, next}]`. Timed events in `[today, today + weeks]` with no `module_id` and no override row (overrides with NULL count as filed), `count >= feeds.MIN_EVENTS`, sorted by `next`.
  - `gr.unfiled_deadlines() -> list[dict]`: open deadlines with `module_id is None`.

- [ ] **Step 1: Write the failing tests**

```python
def test_unfiled_lists_series_until_filed(gr, store, ol):
    sync_uni(ol)
    titles = {s["title"] for s in gr.unfiled_series(date(2026, 11, 20))}
    assert "Spectroscopy" in titles
    spec = gr.add_module("Spectroscopy")
    assert "Spectroscopy" not in {s["title"] for s in gr.unfiled_series(date(2026, 11, 20))}

def test_deleting_a_module_unfiles_its_overrides(gr, store, ol):
    sync_uni(ol)
    mid = gr.add_module("Projects")
    gr.file_series("Summer project chat", mid)
    gr.delete_module(mid)
    assert "Summer project chat" in {s["title"] for s in gr.unfiled_series(date(2026, 11, 20))}
```

(If the fixture has "Summer project chat" only once, swap in a title that appears 2+ times.)

- [ ] **Step 2: Run them to check they fail**

Run: `pytest tests/test_grades.py -k unfiled -q`
Expected: FAIL

- [ ] **Step 3: Implement `unfiled_series`, `unfiled_deadlines` and the `delete_module` cleanup**

- [ ] **Step 4: Build the UI**

- **Links expander** (module page): a Code text input, a "Lecture titles contain" text input (`match`), a Canvas course selectbox (`detected_courses` plus "None"), and a list of this module's linked series, each with a "Not this module" button (`file_series(title, None)`).
- **Unfiled card** (Modules page): each series shows `title · N sessions · next <day>` with a module selectbox (options: modules plus "Not a module") that calls `file_series`. Each deadline gets a module selectbox that calls `store.update_deadline(did, module_id=...)`.

- [ ] **Step 5: Run tests and check by eye**

Run: `pytest -q`
Expected: PASS. Then run `scripts/seed_demo.py` with the app, open Modules: the Unfiled card shows, and filing a series removes it and puts its lectures on that module's page.

- [ ] **Step 6: Commit**

```bash
git add venato/blocks/grades.py venato/ui/module_page.py venato/ui/grades.py tests/test_grades.py
git commit -m "Modules: Links panel and Unfiled list to fix links after setup"
```

---

### Task 4: The module as a tag (codes resolve to its category)

**Files:**
- Modify: `venato/store/categories.py:131-146` (`resolve_category`)
- Modify: `venato/ui/review.py:314-331` (`render`: a "Study by module" section after `_time`)
- Test: `tests/test_grades.py`, `tests/test_review.py`

**Interfaces:**
- Consumes: `gr_modules.code`, `gr_modules.category_id`, `gr.module_hours(m, ctx)`.
- Produces: `resolve_category(label=None, category=None)` also returns a module's `category_id` when `category`, or failing that the whole `label`, or a word in it, equals a module code under `feeds.norm_code`. Existing exact category-name matches win first.

- [ ] **Step 1: Write the failing tests**

```python
def test_module_code_resolves_to_its_category(gr, store):
    mid = gr.add_module("Organic Chemistry", code="CHEM50001")
    cat = gr.get_module(mid)["category_id"]
    assert store.resolve_category(category="chem 50001") == cat
    assert store.resolve_category(label="CHEM50001 problem sheet") == cat
    assert store.resolve_category(label="Lunch") != cat

def test_review_shows_study_by_module(gr, store, ...):
    # follow the AppTest pattern already in tests/test_review.py
    # assert "Study by module" and the module name appear when grades is on and a module exists
```

- [ ] **Step 2: Run them to check they fail**

Run: `pytest tests/test_grades.py tests/test_review.py -k "module" -q`
Expected: FAIL

- [ ] **Step 3: Implement the code lookup in `resolve_category`** (SQL on `gr_modules`, guarded by `OperationalError`) **and the Review section**

The Review section has one `kit.bars` row per module: this week's done against its goal, as on the module page. It only shows when `"grades" in blocks.chosen_keys()` and there's at least one module with a category.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_grades.py tests/test_review.py tests/test_focus.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add venato/store/categories.py venato/ui/review.py tests/test_grades.py tests/test_review.py
git commit -m "Modules: module codes work as categories; Review shows study by module"
```

---

### Task 5: Show the links on each card

**Files:**
- Modify: `venato/blocks/grades.py` (`link_summary`)
- Modify: `venato/ui/grades.py:183-237` (`_facts` adds the line; `_module_card` drops the "Assessments and settings" toggle, since Links and settings live on the module's page)
- Test: `tests/test_grades.py`

**Interfaces:**
- Consumes: `gr.week_events`, `gr.open_deadlines`, `gr.canvas_courses`.
- Produces: `gr.link_summary(m, today: date, weeks: int = 8) -> {"lectures": int, "deadlines": int, "canvas": str | None}`. `lectures` counts timed events in the next `weeks`; `canvas` is the linked course's label.

- [ ] **Step 1: Write the failing test**

```python
def test_link_summary(gr, store, ol):
    sync_uni(ol)
    mid = gr.add_module("Organic Chemistry", code="CHEM50001")
    s = gr.link_summary(gr.get_module(mid), date(2026, 11, 20))
    assert s["lectures"] > 0 and s["canvas"] is None
    empty = gr.add_module("Nothing On")
    assert gr.link_summary(gr.get_module(empty), date(2026, 11, 20))["lectures"] == 0
```

- [ ] **Step 2: Run it to check it fails**

Run: `pytest tests/test_grades.py -k link_summary -q`
Expected: FAIL

- [ ] **Step 3: Implement `link_summary`; render it in `_facts`**

Copy: `:material/link: 12 lectures · 4 deadlines · Canvas: 20501.202610`. When `lectures == 0`: `:orange[No lectures found. Open it and set its code or title in Links.]`

- [ ] **Step 4: Run the full suite**

Run: `pytest -q`
Expected: PASS (update `test_tools_quick_and_page` if it clicked the removed toggle)

- [ ] **Step 5: Commit, then update docs**

Add one CHANGELOG line per task under Unreleased. Update `HANDOVER.md` §4b with the matching priority and the `gr_event_links` / `modules_dismissed` storage.

```bash
git add venato/blocks/grades.py venato/ui/grades.py tests/test_grades.py CHANGELOG.md HANDOVER.md
git commit -m "Modules: each card shows what's linked and flags missing lectures"
```

---

**Out of scope:** "Move to module" on the timetable's event popup. The popup is the JS timetable component, which isn't worth the cost while the Unfiled list and Links panel cover the same fix.
