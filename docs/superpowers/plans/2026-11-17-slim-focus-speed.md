# Slimmer download, student focus, faster pages — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut the installer by ~440 MB, cut Venato down to a student-focused core, and make the pages that change most stop rerunning the whole app.

**Architecture:** Generic work goes on `venato-app` branch `claude/funny-shannon-v696o7` (Tasks 1–10). Removed features are first moved into self-contained block files, so the private copy can keep them with no edits to shared files (Task 11). Speed comes from a data-version cache, `st.fragment` around the busy widgets, and local-first JS components, all chosen from measured numbers.

**Tech Stack:** Python 3.13, Streamlit 1.66.1 (components v2, `st.fragment`, `st.cache_data`), Altair (already a Streamlit dependency), SQLite, PyInstaller.

**Spec:** the conversation of 2026-11-17 (user's list: smaller download, three tiers, Streamlit quick wins). Assistant work is out of scope.

## Decisions to confirm before building

| # | Question | Recommendation |
|---|---|---|
| D1 | Daily Log's mood/sleep/energy/water: the list doesn't say. Habits and Journal are on the same page today. | **Optional**, as one "Daily Log" block (habits + journal + mood). Not split into three blocks. |
| D2 | Cut down isn't in the list. | **Gone from public**, kept in private. |
| D3 | Stats isn't in the list, but it holds the weekly review history. | **Core**, renamed **Review**. |
| D4 | Whisper in the installers: download inside the app, or drop it? A downloaded engine is unsigned native code, which a signed and notarised Mac app refuses to load without weakening its security settings. | **Drop it from the installers.** The mic button uses the system's own dictation (Fn Fn on Mac, Win+H on Windows). Whisper stays for source installs via `./setup.sh --voice`. |
| D5 | Can pandas go? **No.** Streamlit itself requires pandas (80 MB) and pyarrow (170 MB). | Remove plotly only (61 MB), and use Altair, which Streamlit already ships. |
| D6 | Users of the public app who have data in removed features. | Tables and data stay in `life.db` untouched (no `DROP`); only the pages go. Mentioned in the CHANGELOG. |

## Measured sizes (installed, Linux, current `requirements.txt`)

| Goes | MB | Stays (Streamlit needs it, or out of scope) | MB |
|---|---|---|---|
| ctranslate2 + .libs | 148 | claude_agent_sdk (assistant: out of scope) | 280 |
| av + .libs | 128 | pyarrow | 170 |
| onnxruntime | 78 | pandas | 80 |
| plotly + narwhals | 66 | numpy + .libs | 70 |
| tokenizers, huggingface_hub, hf_xet | 30 | streamlit | 36 |
| **Total** | **~450** | | |

## Global Constraints

- Generic work: `venato-app` branch `claude/funny-shannon-v696o7` only. Never put private code or history in `venato-app`.
- Commits use `spencertomj1-hue@users.noreply.github.com`.
- Tests always set `VENATO_DATA_DIR` to a temporary folder (the existing fixtures do). Run with `.venv/bin/python -m pytest -q -p no:logging tests`.
- No `DROP TABLE` or data deletion for removed features.
- No new runtime dependencies. Altair comes with Streamlit.
- Copy follows the current UI voice: short, plain, British spelling.
- Every page still passes WCAG AA contrast in light and dark (charts included).

## Review Focus

1. **settings.json lists keys of removed blocks** (`"blocks": ["food", "network", ...]`): the app starts, ignores them, and Home keeps the rest in order. Test in Task 4.
2. **A to-do or habit ticked inside a fragment that a goal on the same screen depends on**: the goal bar updates without a manual refresh. Test in Task 8.
3. **Data written outside a page** (Outlook sync, focus session ending, Undo restoring the database): cached stats and search show the new data on the next run. Test in Task 7.
4. **Mic button on an install without Whisper**: no exception; shows the dictation tip and focuses the chat box. Test in Task 6.
5. **Existing database holding `applications` / `net_*` rows when those blocks are absent**: no error at start-up, and search returns no Application/Person results. Test in Task 3.

---

### Task 1: Page timing script and baseline

**Files:**
- Create: `scripts/profile_pages.py`
- Create: `docs/perf.md` (results table, before and after)

**Interfaces:**
- Produces: `python scripts/profile_pages.py [--runs 5] [--pages Home,Timetable]` prints `page  median_ms  p90_ms` per page.

- [ ] **Step 1:** Write the script: a temp `VENATO_DATA_DIR` seeded by `scripts/seed_demo.py`, `wizard_done=True`, every block switched on; for each key in `app.PAGES`, set `session_state["page"]` with `streamlit.testing.v1.AppTest` and time `at.run()` N times (discard the first, which is cold).
- [ ] **Step 2:** Also time one widget interaction per page that has one (tick a to-do on Home, tick a habit in Daily Log, start/stop Focus, switch Plan/Actual on Timetable).
- [ ] **Step 3:** Run it, write the table into `docs/perf.md` under "Before", and mark the three slowest pages/interactions. Tasks 8–9 target those three plus the widgets named in the spec.
- [ ] **Step 4:** Commit `perf: page timing script and baseline`.

### Task 2: Block hooks for search and the weekly review

So features can leave shared code entirely and still show in search and the review.

**Files:**
- Modify: `venato/blocks/__init__.py` (Block fields), `venato/store.py:2630-2675` (`_SEARCH`, `search`), `venato/review.py:110-165`, `venato/ui/review.py:90-100`, `venato/ui/search.py:15-40`
- Test: `tests/test_blocks.py`, `tests/test_search.py`, `tests/test_review.py`

**Interfaces:**
- Produces on `Block`:
  - `search: dict[str, tuple[str, str]]` — kind → `(select, haystack)` in `store._SEARCH`'s shape, plus `search_open: Callable[[dict, dict], None] | None` (result, session_state) to route a click.
  - `search_icons: dict[str, str]` — kind → Material icon name.
  - `review: Callable[[date, date], dict] | None` — returns `{"title": str, "lines": list[str]}`; empty `lines` = nothing to show.
- `store.search()` loops core `_SEARCH` plus every enabled block's `search`. `review.summary()` adds `"sections": [ {key, title, lines}, ... ]`; `review.as_text()` and `ui/review.py` print each section.

- [ ] **Step 1:** Failing tests: `test_block_search_kind_found` (a fake block registered with a `search` entry over a temp table is found by `store.search`), `test_disabled_block_not_searched`, `test_review_sections_from_block` (fake block's lines appear in `summary(...)["sections"]` and in `as_text`).
- [ ] **Step 2:** Implement. Leave the existing Application/Person/Group/Met entries where they are for now (Task 3 moves them).
- [ ] **Step 3:** Full suite passes. Commit `blocks: search and review hooks`.

### Task 3: Make Applications and Network self-contained blocks

Everything about them moves into their block files, so deleting those files removes them cleanly.

**Files:**
- Create: `venato/blocks/applications.py`, `venato/blocks/network.py`
- Modify: `venato/blocks/core.py` (remove both Blocks), `venato/store.py` (move schema at 200–231 and 252–270, the `net_groups` migration at 279 and seed at 311, functions 692–750 and 2295–2560, `_SEARCH` entries 2638–2652), `venato/tools.py` (move 1130–1300 and 1498–1590), `venato/assistant.py` (move the Network and Applications prompt paragraphs at 290–325 into each Block's `prompt`, and their tool specs into `tools`), `venato/review.py` (people → Network's `review` hook), `venato/ui/search.py` (routing → `search_open`)
- Test: `tests/test_applications.py`, `tests/test_network.py` (update imports), new `tests/test_removed_blocks.py`

**Interfaces:**
- `venato.blocks.applications` exposes the store and tool functions that used to be `store.add_application` … `tools.delete_application`, same names and signatures. `venato.blocks.network` likewise for people, groups, links, interactions. Each Block sets `schema`, `migrate`, `tools`, `prompt`, `search`, `search_icons`, `search_open`, and Network sets `review`.
- After this task `store.py`, `tools.py`, `assistant.py`, `review.py`, `ui/search.py` contain no `application`, `net_` or `person` code.

- [ ] **Step 1:** Move the code; update the two feature test files to import from the block modules. They pass unchanged otherwise.
- [ ] **Step 2:** Failing test `test_removed_blocks.py::test_old_tables_without_blocks`: a DB with rows in `applications` and `net_people`, both blocks absent from `all_blocks()` (monkeypatch), `store.init_db()` succeeds, `store.search("Acme")` has no Application or Person results, `review.summary(...)` has no Network section.
- [ ] **Step 3:** Make it pass. `grep -n "applic\|net_\|person" venato/store.py venato/tools.py venato/assistant.py venato/review.py` finds nothing feature-related.
- [ ] **Step 4:** Full suite passes. Commit `blocks: Applications and Network carry their own tables, tools, search and review`.

### Task 4: Three tiers

**Files:**
- Modify: `venato/blocks/__init__.py`, `venato/blocks/core.py`, `venato/blocks/focus.py`, `venato/blocks/grades.py`, `venato/ui/blocks_ui.py`, `venato/ui/settings_ui.py:265-300` (wizard), `venato/ui/stats.py` (title "Review")
- Test: `tests/test_blocks.py`, `tests/test_setup.py`

**Interfaces:**
- Core (`core=True`): `timetable`, `goals` (to-dos, deadlines), `focus`, `grades`, `stats` (sidebar name **Review**). Optional: `log` (Daily Log), `money`, `workouts`.
- `log` keeps `default=True` so existing installs with no `"blocks"` saved keep it. New installs: the wizard saves `blocks=[]` when it finishes, so they get core only.
- Wizard: the "Choose your blocks" step goes. Settings → Blocks lists core blocks as "Always on" (no toggle, still re-orderable for Home) and optional blocks with toggles.

- [ ] **Step 1:** Failing tests: `test_core_always_on` (saved `blocks=[]` → `chosen_keys()` is exactly the five core keys), `test_unknown_saved_keys_ignored` (saved `["food","network","money"]` → core + `money`, no error; Review Focus 1), `test_wizard_saves_core_only` (AppTest through the wizard → settings `blocks == []`), `test_wizard_has_no_blocks_step`, `test_existing_install_keeps_log` (no `"blocks"` key → `log` on).
- [ ] **Step 2:** Implement. Sidebar order: Home, Timetable, Goals, Focus, Grades, Review, then optional ones, Settings.
- [ ] **Step 3:** Full suite passes. Commit `blocks: core, optional, and a shorter setup`.

### Task 5: Remove the cut blocks from the public app

**Files (delete):**
- `venato/blocks/{food,recipes,health,involvement,cutdown,applications,network}.py`
- `venato/ui/{food,recipes,health,involvement,cutdown,applications,network}.py`
- `venato/ui/components/{apps,network}_component.{js,css}`
- `tests/test_{food,health,involvement,cutdown,applications,network}.py` (and any recipes tests inside `test_food.py`)
- Modify: `README.md` (features table, screenshots that show removed pages), `HANDOVER.md` (file list), `CHANGELOG.md` (note D6), `packaging/venato.spec` (`defusedxml` only if Health was its sole user), `requirements.txt`, `scripts/seed_demo.py`, `venato/ui/settings_ui.py:280,516` (copy that mentions people/network)

- [ ] **Step 1:** Delete, then `grep -rn "food\|recipe\|health\|involvement\|cutdown\|applications\|network" venato app.py scripts tests` and fix every remaining reference (words like "local network address" in `outlook.py` stay).
- [ ] **Step 2:** `pyflakes venato app.py` clean; full suite passes; `scripts/profile_pages.py` runs (every page renders).
- [ ] **Step 3:** Commit `Remove Food, Recipes, Health, Involvement, Cut down, Applications and Network from the public app`.

### Task 6: Whisper out of the installers; system dictation

**Files:**
- Create: `requirements-voice.txt` (`faster-whisper==1.2.1`, `sounddevice==0.5.6`)
- Modify: `requirements.txt` (remove those two), `venato/voice.py`, `venato/ui/chat.py:70-120`, `venato/setup_checks.py:80-95`, `venato/ui/settings_ui.py` (mic tab), `packaging/venato.spec:36-38` (drop `faster_whisper`, `ctranslate2`, `sounddevice`, `_sounddevice_data`; add `excludes` `onnxruntime`, `av`, `tokenizers`, `huggingface_hub`), `setup.sh`, `setup.ps1` (`--voice` / `-Voice` installs `requirements-voice.txt`), `.github/workflows/tests.yml` (install both files so voice tests still run), `README.md`
- Test: `tests/test_voice.py`, `tests/test_chat_app.py`

**Interfaces:**
- `voice.available() -> bool`: True when `faster_whisper` and `sounddevice` import.
- `voice.dictation_tip() -> str`: Mac "Press Fn twice (or 🌐 twice) to dictate", Windows "Press Win + H to dictate", else "".
- Mic button: `available()` → current recording flow; otherwise focuses the chat box and shows `dictation_tip()` for a few seconds. Settings → Voice: the mic test only when `available()`; otherwise the tip, and for source installs a line on `./setup.sh --voice`.

- [ ] **Step 1:** Failing tests: `test_mic_without_whisper_shows_tip` (monkeypatch `available` False; AppTest click mic → no exception, tip text shown; Review Focus 4), `test_voice_available_false_when_missing` (import of `faster_whisper` forced to fail → False).
- [ ] **Step 2:** Implement. `voice.py` imports `numpy`, `sounddevice` and `faster_whisper` only inside functions.
- [ ] **Step 3:** Build the Mac/Windows bundle in CI (`release.yml` on the branch's PR trigger, `packaging/**` changed) and record the bundle size in `docs/perf.md`, before vs after. Expect roughly 380 MB less from this task.
- [ ] **Step 4:** Commit `Voice: system dictation by default, Whisper as an optional extra`.

### Task 7: Plotly → Altair

**Files:**
- Modify: `venato/ui/kit.py` (chart helpers), `venato/ui/{stats,review,focus,workouts,money,grades}.py`, `requirements.txt` (remove `plotly`), `packaging/venato.spec` (remove `plotly` from `collect_all`)
- Test: `tests/test_code.py`

**Interfaces:**
- `kit.line_chart(df, x, y, color=None, y_title=None, height=260)`, `kit.bar_chart(df, x, y, color=None, stack=False, horizontal=False, height=260)`, `kit.show(chart)` (`st.altair_chart(chart, use_container_width=True, theme="streamlit")`). Category colours come from the existing category colours passed as an Altair `scale(domain, range)`.
- Any chart the helpers don't cover (Grades' target marker, Workouts' 1RM trend) is built with Altair layers in its own module.

- [ ] **Step 1:** Failing test `test_code.py::test_no_plotly`: no file under `venato/` or `app.py` imports `plotly`.
- [ ] **Step 2:** Convert each chart, one module at a time, comparing a screenshot in light and dark with the plotly version (Playwright on `streamlit run` with demo data) for the same series, colours and axes.
- [ ] **Step 3:** Full suite passes, `pip uninstall plotly` in the venv and every page still renders via `scripts/profile_pages.py`. Commit `Charts: Altair instead of plotly`.

### Task 8: Data-version cache

**Files:**
- Modify: `venato/store.py:80-90` (`db()`), `venato/undo.py` (restore), `venato/ui/kit.py`, and the call sites chosen from Task 1 (at least `store.get_stats`, `store.search`, `review.summary`, `pace.Ctx` data loads)
- Test: `tests/test_store.py`, new `tests/test_cache.py`

**Interfaces:**
- `store.data_version() -> int`: bumped in `db()` when `conn.total_changes > 0` at commit, and by `undo.restore()`. Process-wide, guarded by a `threading.Lock` (the Outlook sync and notify threads write too).
- `kit.cached(fn)`: wraps `fn` in `st.cache_data(max_entries=64)` with `data_version()` and `store.load_settings()`'s mtime as hidden extra key parts. Same signature as `fn`.

- [ ] **Step 1:** Failing tests: `test_version_bumps_on_write`, `test_version_unchanged_on_read`, `test_version_bumps_on_undo_restore`, `test_cached_stats_see_new_log` (cached `get_stats` → add a log → next call includes it; Review Focus 3), `test_cached_sees_background_thread_write` (write from a `threading.Thread`).
- [ ] **Step 2:** Implement and apply `kit.cached` to the functions chosen from Task 1's numbers. Leave a function uncached if caching it doesn't save ≥20 ms per run.
- [ ] **Step 3:** Full suite passes. Commit `perf: cache reads until the data changes`.

### Task 9: Fragments and local-first components

**Files:**
- Modify: `venato/ui/todos.py:61-85`, `venato/ui/daily_log.py:183-240` and its day card, `venato/ui/focus.py:50-240`, `venato/ui/timetable.py`, `venato/ui/components/timetable_component.js`, plus the three slowest from Task 1
- Test: `tests/test_todos_app.py`, `tests/test_focus.py`, `tests/test_goal_time_app.py`, new `tests/test_fragments.py`

**Interfaces:**
- Each busy widget is drawn by a function decorated `@st.fragment`. After saving, a fragment calls `kit.rerun_app_if(changed: set[str])`, which does `st.rerun(scope="app")` only if something outside the fragment depends on it: a habit linked to a goal, a to-do linked to a goal, a focus session that wrote to the Actual timetable. Otherwise only the fragment reruns.
- Timetable component: applies a move/stretch/add/delete to its own DOM straight away, sends the op, and keeps the op pending until it sees its `opId` in `data.acked` (the pattern `todos_component.js` already uses). A rejected op rolls back and shows the error.

- [ ] **Step 1:** Failing tests: `test_todo_tick_reruns_fragment_only` (AppTest: tick an unlinked to-do; a counter incremented in `page_home` outside the fragment does not move), `test_linked_habit_updates_goal` (tick a habit linked to a goal on Home → the goal's progress text changes in the same run; Review Focus 2), `test_focus_stop_updates_actual`.
- [ ] **Step 2:** Implement fragments for: Home to-dos, habit ticks (Home and Daily Log), Daily Log day card, Focus timer and Home focus widget, then the Task 1 slowest three.
- [ ] **Step 3:** Timetable ops local-first. Manual check in a browser: drag a block, it moves with no flicker; force a save error, it moves back with a message.
- [ ] **Step 4:** Full suite passes. Commit `perf: fragments and local-first timetable`.

### Task 10: Measure again, docs, push

- [ ] **Step 1:** Run `scripts/profile_pages.py`; add "After" to `docs/perf.md` with the change per page/interaction and the bundle sizes from Task 6.
- [ ] **Step 2:** README: new pitch line for students, features list by tier, voice section, size. HANDOVER: blocks tiers, hooks, cache, fragment rule. CHANGELOG entry.
- [ ] **Step 3:** Full suite on the branch. Push `claude/funny-shannon-v696o7` to `venato-app`. Ask the user whether to open a PR or merge to `main`.

### Task 11: Private copy keeps the cut features

On `venato-private` branch `claude/funny-shannon-v696o7`.

- [ ] **Step 1:** `git fetch` the public branch and merge it. The deletions from Task 5 come through.
- [ ] **Step 2:** Restore the seven block files, their UI modules, the two components and their tests from the pre-merge commit (`git checkout <pre-merge> -- <paths>`), using the Task 3 versions of `applications.py` and `network.py` (taken from the public branch's commit before Task 5). Because they are self-contained, no shared file changes.
- [ ] **Step 3:** Convert their charts, and `ui/uni_stats.py` and `ui/problem_sets.py`, to the `kit` Altair helpers (Task 7's `test_no_plotly` must pass here too).
- [ ] **Step 4:** Owner's `settings.json` already lists their blocks, so nothing to change there. Full suite passes. Commit `Keep Food, Recipes, Health, Involvement, Cut down, Applications and Network in the private copy`, push the branch, and ask before merging to private `main` (the owner's app only updates from there, via `venato-update`).
