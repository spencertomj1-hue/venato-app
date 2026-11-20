# Blank slate, goal-led and student onboarding, Modules, a Home you arrange: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new user starts with nothing preset. Setup asks whether they're a student. Students get their uni timetable,
Canvas deadlines and modules pulled in. Everyone sets 3/6/12-month goals and picks what to track, and that fills the app.
Everything about a module lives on one page. A deadline can be planned back from its due date. Home is an
iPhone-style grid you arrange yourself, and it starts focused on today.

**Architecture:** Generic, so it's built on `venato-app` (branch `claude/vigilant-mccarthy-6h9s5z`). Each phase is its own PR,
merged to public main, then `git fetch public && git merge public/main` into `venato-private`. Modules stay in the
Grades block's tables, linked to the timetable by `gr_modules.category_id` and to deadlines and events by `module_id`.
Deadline plans reuse the existing hours goals. Home widgets are separate from blocks.

**Tech Stack:** Python 3.13, Streamlit 1.66.1, SQLite, icalendar + recurring_ical_events.

## Decisions (settled)

| # | Decision |
|---|---|
| D1 | The Grades page is renamed **Modules**. The block key stays `grades`. |
| D2 | Deadlines get an optional `due_time` (Canvas gives 23:59). Countdowns and reminders use it. |
| D3 | Canvas assignments become deadlines linked to their module, not assessments. "Counts towards my grade" turns one into a weighted assessment. |
| D4 | Search moves to the top of the sidebar. |
| D5 | No AI in setup. Suggestions come from a keyword map. A one-time "Needs you" card after 7 days offers the assistant. |
| D6 | Study hours default to 6 h/week per module: one slider, with a per-module override. |
| D7 | **Core blocks**, on for new installs and removable: Timetable, Goals, Review, Focus, Daily Log, plus Modules for students. **Extras**, folded under More blocks in Settings and suggested in setup only when a goal matches: Workouts (public); Food, Network, Applications, Problem Sets (private). |
| D8 | **Chopped:** Money (public); Cut down, Recipes, Health data, Involvement (private). Code, pages, tools and tests go. Their tables stay in the database, unread. Problem Sets and Applications stay private-only. |
| D9 | Daily Log is a journal with optional sleep and water. Mood, energy and productivity are removed. It has no setup step of its own: habits and sleep/water get suggested in "What would you track". |
| D10 | Home is a hidden grid. Widgets snap to set sizes and reflow, like an iPhone home screen. Moving is tap-to-move (no drag), animated so it looks smooth. |
| D11 | Existing installs: no wizard (`wizard_done`), no data deleted. Blank-slate seeding changes affect new databases only. Chopped blocks disappear from their sidebar. |

## Global constraints

- Generic code only in `venato-app`. Commits use `spencertomj1-hue@users.noreply.github.com`.
- Tests set `VENATO_DATA_DIR` to a temp folder. Run `.venv/bin/python -m pytest -q -p no:logging tests`.
- Migrations only add columns or tables (`_add_column`). Nothing is dropped.
- Calendar links stay in the system secret store.
- Copy is short, plain and in British spelling. WCAG AA in light and dark.

## Review focus

1. A Canvas deadline the student ticked done, deleted or re-dated is **not** reset by the next sync (`uid` + `deadlines_hidden`).
2. An assignment re-dated in Canvas moves the Venato deadline and its plan's goal due date.
3. Uni timetable events count once in goal hours, under their module's category.
4. Deleting a module only clears the links. Its category, deadlines and events stay.
5. When a deadline is ticked done, its plan's goal closes and its suggested sittings go.
6. With zero categories, zero blocks or zero widgets, every page still renders with a clear empty state.
7. Nothing in an existing install's data gets deleted or rewritten. That includes the chopped blocks' tables and the old mood/energy/productivity columns.

## How modules are found without typing

1. **Canvas feed:** `SUMMARY` ends with the course in brackets (`Essay 1 [ENG2001]`), and `URL` contains `/courses/<id>/`. Distinct course ids give the courses.
2. **Uni timetable feed:** weekly recurring events sharing a module code (`\b[A-Z]{2,5}\s?\d{3,5}[A-Z]?\b`). Fallback: group by title with Lecture/Seminar/Lab/Tutorial stripped.
3. **Merge** the two by code. The student ticks, renames or removes. Credits default from the uni-wide setting. With no feeds, a plain "Add a module" box.

---

### Phase 0: Check the feed formats

**Files:** create `tests/fixtures/canvas_sample.ics`, `tests/fixtures/uni_timetable_sample.ics` (anonymised).

- [ ] Get a real Canvas feed and a real uni timetable feed. Record the shape of `SUMMARY`, `URL`, `DTSTART` (date or datetime) and `UID`.
- [ ] Anonymise them into fixtures.
- [ ] Adjust the detection rules above to what's really there before Phase 2.

### Phase 1: Blank slate and chop blocks (PR 1)

**Files:** `store/categories.py`, `store/schema.py:180-187`, `blocks/__init__.py`, `blocks/workouts.py:23`, delete `blocks/money.py`, `ui/money.py`, `tests/test_money.py`. Money references in `ui/kit.py`, `tests/test_setup.py`, `tests/test_todos_app.py`, `tests/test_blocks.py`.

- [ ] Stop seeding `DEFAULT_CATEGORIES` / `DEFAULT_LABEL_MAP` on new databases. Rename them `EXAMPLE_CATEGORIES` / `EXAMPLE_LABEL_MAP`, kept for suggestions only.
- [ ] Zero categories must work everywhere: `outlook_category()` (no category means grey), focus `_maybe_timetable`, timetable add-block, goal-hours pickers, Review charts. Each gets an "Add a category" empty state.
- [ ] Workouts stops auto-seeding. Its empty state offers "Add examples" next to "Add your own".
- [ ] `Block.core: bool`. `STARTER` = the core keys (D7). Modules is added by the student branch of setup.
- [ ] Delete the Money block (D8). Leave its tables in place, with no migration.
- [ ] **Private follow-up (merge PR):** delete `cutdown.py`, `recipes.py`, `health.py`, `involvement.py` and their `ui/`, tools and tests. Check whether Food's meal planner calls Recipes (the shopping list is "filled from your meal plan") and cut that link cleanly.
- [ ] Tests: a fresh database has 0 categories, 0 label defaults and 0 exercises, and every page renders. Settings that still list a chopped block load without error.

### Phase 2: Link modules, categories, deadlines and events; import the feeds (PR 2)

**Files:** `blocks/grades.py` (migrate), `store/schema.py`, `store/deadline.py`, `store/outlook.py`, `store/categories.py`, create `venato/feeds.py`, modify `venato/outlook.py`. Tests: `test_grades.py`, `test_deadlines.py`, `test_outlook.py`, create `test_feeds.py`.

- [ ] `gr_modules.category_id`. Creating a module creates a category (group "Modules", next free colour). Renaming a module renames its category.
- [ ] `deadlines`: add `module_id`, `due_time`, `source`, and `uid` (unique when set). New table `deadlines_hidden (uid)`.
- [ ] `tt_outlook.module_id`. `outlook_category()` uses the module's category when there is one.
- [ ] `goal_hours`: each event counts under its own category.
- [ ] `detect_modules(events)` and `import_canvas(events)`: upsert by `uid`, skip hidden uids, never overwrite `done`, notes or a title the student edited.
- [ ] `check_any_link` recognises `instructure.com` as Canvas. Sync sends Canvas feeds to `import_canvas` and tags timetable events with `module_id` by code.
- [ ] Tests (with the Phase 0 fixtures): module ↔ category created and renamed together. Module hours counted once. Deleting a module only clears links. Modules detected. Re-syncing is idempotent. A re-dated assignment moves. Ticked or deleted assignments stay as the student left them.

### Phase 3: Daily Log becomes a journal (PR 3)

- [ ] Sleep and water are optional: switches in Settings → Daily Log, off on new installs. Off means hidden everywhere.
- [ ] Remove mood, energy and productivity from `ui/daily_log.py`, `components/calendar_component.js`, `store/stats.py`, `ui/stats.py`, `review.py`, `ui/review.py`, `tools/daily_log.py`, `assistant.py`, `quick.py`, `store/history.py` (CSV), `store/journal.py`, `ui/settings_ui.py` and the `blocks/core.py` blurbs (Daily Log, plus Review's "mood and sleep charts").
- [ ] The old columns stay, unread. No migration.
- [ ] The page leads with the journal box (today's prompt), with sleep and water beside it when on. The calendar marks days with an entry. Habits stay on this page.
- [ ] Tests: saves notes, sleep and water. No mood, energy or productivity in the UI, tools or CSV. The switches hide sleep and water.

### Phase 4: iPhone-style Home (PR 4)

**Files:** `ui/home.py`, `blocks/__init__.py` (`Block.widgets`, `Block.needs`), `ui/goal_time.py` (`needs_you`), `venato/undo.py`, `app.py` (sidebar search), `ui/search.py`. Tests: `test_blocks.py`, `test_chat_app.py`, create `test_home_layout.py`.

**Widgets:** `timetable_today`, `ask`, `needs_you`, `todos`, `deadlines`, `goals`, `habits`, `journal`, `focus`, `modules`, plus whatever extra blocks declare in `Block.widgets`, which replaces `Block.home`. `Block.needs` returns items for Needs you.

**Grid:** a hidden 12-column grid. The layout is one ordered list, saved in `settings.json`:
`home: [{"w": "timetable_today", "size": "l"}, {"w": "needs_you", "size": "s"}, ...]`.
Sizes are S = ⅓, M = ½, L = ⅔, Full. The renderer packs widgets left to right into rows (`st.columns` ratios), the
way iPhone icons flow. Moving a widget changes its place in the list, and the others reflow. A missing key gives the
default layout. Unknown or switched-off widgets are skipped.

**Default layout** is today's Essentials Home: timetable (L) | Ask, Needs you, To-dos (S, stacked in one column cell). Deadlines and the rest are hidden until added.
*Stacking:* a cell can hold a vertical stack of widgets, so the default layout fits the model: `{"stack": [...], "size": "s"}`.

**Arrange mode ("jiggle"):**
- [ ] A `:material/dashboard_customize:` tertiary button in Home's top-right corner turns it on. Widgets wobble gently (CSS, switched off under `prefers-reduced-motion`).
- [ ] Tap a widget to pick it up (highlighted). Tap another widget to drop it there, and everything reflows. Each widget also gets a slim bar: size −/+, ✕ hide, ← / → (one step back or forward, for keyboard users).
- [ ] "+ Add widget" picks from hidden widgets and puts the new one at the end.
- [ ] "Done" and "Reset" replace the Arrange button. Every change saves straight to `settings.json`, with undo via `venato/undo.py`.
- [ ] Widgets show their real content while you arrange.

**Smooth moves (FLIP):**
- [ ] Wrap each widget in `st.container(key=f"hw_{name}")`.
- [ ] A small script injected once records each `.st-key-hw_*` box position before the rerun and, once the new DOM settles (MutationObserver), animates each widget from its old box to its new one (`transform`, ~200 ms ease-out). Size changes animate the same way.
- [ ] **Spike this first.** If Streamlit's rerender fights it, fall back to a fade-in on the moved widget. Instant moves never break anything.

**Needs you and search:**
- [ ] Needs you gathers: goals behind or short, deadlines in the next 7 days with no plan or behind on it, unconfirmed past days, block `needs` items, and the D5 assistant card. When empty it says "Nothing needs you. Go touch grass."
- [ ] Search moves to the sidebar (D4).
- [ ] Tests: the default layout matches Essentials. A custom list packs into the right rows and widths. Unknown or disabled widgets are skipped. Over-wide rows wrap. Reset restores the default. Undo reverts a move.

### Phase 5: Modules page and deadline plans (PR 5)

**Files:** `ui/grades.py` (becomes Modules), `blocks/grades.py`, `ui/deadlines.py`, `store/goals.py` (`deadline_id`), `ui/goal_time.py`. Tests: `test_grades.py`, `test_deadlines.py`, `test_goal_time_app.py`.

- [ ] Modules list: colour, next deadline, hours this week (done / planned / goal), current mark vs target.
- [ ] One module's page: this week's lectures, upcoming deadlines (with Plan), assessments with "you need X% on the rest", hours this week and this term, its timetable blocks, and "Fit time".
- [ ] Clicking a deadline or lecture anywhere opens its module.
- [ ] Problem Sets (private) is left as it is. A later task can fold it into Modules.
- [ ] **Plan** (replaces "Make time"): total hours **or** hours a week, the module (pre-filled), and a finish-by day (defaults to the day before it's due). It creates an hours goal (target, due, the module's category, labelled with the deadline's title), so pace, carry-over, sittings and "can't make it" all come for free.
- [ ] The deadline row shows "6 / 15 h · on track". Done or deleted closes the goal. A Canvas re-date moves the goal.
- [ ] Tests: per-week maths, a missed sitting carried over, done closes the goal.

### Phase 6: Setup wizard (PR 6)

**Files:** `ui/settings_ui.py` (`STEPS`, `wizard`, `_finish`), create `ui/onboarding.py`, create `venato/suggest.py` (keyword map), `tests/test_setup.py`.

**Steps:** Welcome → Are you a student? → *(students: Uni timetable → Canvas → Your modules → Study hours)* → Your goals → What would you track? → Your day → Your first week → Home.
Every step except Welcome can be skipped. "Skip setup" leaves a truly blank app. There's no Assistant or Mic step: those stay in Settings → Assistant.

- [ ] **Student?** Yes turns on Modules and shows the uni steps.
- [ ] **Uni timetable / Canvas:** how to find the link, a paste box, and a preview ("Found N lectures next week" / "N assignments due").
- [ ] **Your modules:** the detected list to tick, rename or remove. Target grade (First / 2:1 / 2:2) set once. An "Add a module" box.
- [ ] **Study hours:** the D6 slider. Creates one weekly hours goal per module.
- [ ] **Your goals:** 3 months / 6 months / 1 year. Free text plus an optional number target. Saved as goals with `due` = today + 3/6/12 months. Students see their module targets listed as goals they already have.
- [ ] **What would you track?** For each goal, keyword-map suggestions (`suggest.py`): habits, categories, sleep/water switches and extra blocks (run/gym → Workouts, Exercise category, "Trained" habit; exam/degree → Study category). All **unticked**, labelled "examples: pick what you want", plus "Add your own". Ticked items link to the goal (`habit_id` / `category_id`).
- [ ] **Your day:** timetable categories. Module categories are already there; the ones implied by the last step are ticked; `EXAMPLE_CATEGORIES` show as chips; "Add your own" takes a name and colour.
- [ ] **Your first week:** suggested sittings for the next 7 days on a mini grid (`goal_time.suggestions_for`), with **Add to my Plan** / Skip.
- [ ] **Home:** prefilled from what they picked (e.g. Modules or Habits widgets added), with a pointer to the Arrange button.
- [ ] `_finish`: core blocks plus the picked extras, assistant off, `wizard_done`.
- [ ] "Run setup again" in Settings only adds things, never deletes.
- [ ] Tests: skipping everything lands on a blank Home with no errors. With the fixture feeds, a student ends up with modules, categories, deadlines, goals and planned blocks. A non-student gets no uni steps. Re-running setup deletes nothing.

### Phase 7: Docs and merge

- [ ] README ("Getting started" for the new setup, Money removed), CHANGELOG, HANDOVER.
- [ ] Full test run. Merge each PR to public main, then into `venato-private`, where the private chops from Phase 1 land and the private extras get `core=False`.
- [ ] Later (separate task): the weekly review asks "still on track for your 3-month goal?".

## Order

Phase 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7. Phases 3 and 4 don't depend on 2 and can run alongside it. Phase 6 needs all of them.
