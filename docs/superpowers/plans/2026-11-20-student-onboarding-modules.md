# Student onboarding, Modules, deadline plans, a focused Home: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new student finishes setup with their uni timetable, Canvas deadlines and modules already in Venato and their first week planned. Everything about a module lives on one page. A deadline can be planned back from its due date. Home shows only today and what needs attention.

**Architecture:** All of it is generic: build on `venato-app` branch `claude/charming-lamport-s47zyt`, merge to public main, then `git fetch public && git merge public/main` into `venato-private`. Modules stay in the Grades block's tables; the link to the timetable is one new column (`gr_modules.category_id`) plus `module_id` on deadlines and calendar events. Deadline plans reuse the existing hours goals (pace, carry-over, suggested sittings) instead of a new planner.

**Tech Stack:** Python 3.13, Streamlit 1.66.1, SQLite, icalendar + recurring_ical_events (already used by `venato/outlook.py`).

## Decisions to confirm before building

| # | Question | Recommendation |
|---|---|---|
| D1 | Grades page name | Rename the page **Modules** (grades live inside each module). Block key stays `grades`. |
| D2 | Deadline times | Add an optional `due_time` (Canvas gives 23:59 etc.). Countdowns and reminders use it when set. |
| D3 | Canvas assignments as Grades assessments | **No.** The feed has no weights. They become deadlines linked to the module; "Counts towards my grade" on a deadline turns it into an assessment with a weight. |
| D4 | Search, once it's off Home | A search box at the top of the sidebar. |
| D5 | Assistant offer | A one-time Home card after 7 days of use: "Want to plan by typing? Switch on the Claude assistant". |
| D6 | Default study hours | 6 h/week per module, one slider for all, per-module override. |
| D7 | "More blocks" | Money, Workouts, Daily Log (public); Food, Recipes, Cut down, Health, Involvement, Network, Applications (private). Folded away in Settings → Blocks; never offered in setup. Anyone who already has them on keeps them. |

## How modules are found without typing (answers "how do we figure out their modules")

1. **Canvas feed:** each assignment's `SUMMARY` ends in the course in brackets, e.g. `Essay 1 [ENG2001]`, and its `URL` contains `/courses/<id>/`. Distinct course ids = their Canvas courses. **Verify on a real feed first (Task 0).**
2. **Uni timetable feed:** recurring weekly events whose titles share a module code (regex like `\b[A-Z]{2,5}\s?\d{3,5}[A-Z]?\b`, e.g. `COMP10120 Lecture`). If no codes match, fall back to grouping by title with the "Lecture/Seminar/Lab/Tutorial" words stripped.
3. **Merge** the two by code. Show the list for the student to tick, rename or remove. Only credits stay unknown: default from the uni-wide setting (e.g. 20), editable later. Fallback: a single "Add a module" text box when there are no feeds.

## Global Constraints

- Generic code only, in `venato-app`. Nothing personal. Commits use `spencertomj1-hue@users.noreply.github.com`.
- Tests set `VENATO_DATA_DIR` to a temp folder (existing fixtures). Run `.venv/bin/python -m pytest -q -p no:logging tests`.
- Migrations only add columns or tables (`_add_column`). No data deleted.
- Existing users (`wizard_done: true`) never see the new wizard. They get "Connect your uni timetable / Canvas" in Settings → Calendars and on the Modules page.
- Calendar links stay in the system secret store, like now.
- Copy: short, plain, British spelling. WCAG AA in light and dark.

## Review Focus

1. A Canvas deadline the student ticked done, deleted or re-dated is **not** reset by the next sync (needs `uid` + hidden list, like `tt_outlook_hidden`).
2. An assignment re-dated in Canvas moves the Venato deadline and its plan's goal due date.
3. Uni timetable events counted once in goal hours, under their module's category, never as well as the default calendar category.
4. A module deleted in Grades: its category, deadlines and events stay; only the link is cleared.
5. A deadline plan whose deadline is ticked done: its goal closes and its suggested sittings disappear.

---

### Task 0: Check the feed formats

**Files:** Create `tests/fixtures/canvas_sample.ics`, `tests/fixtures/uni_timetable_sample.ics` (anonymised).

- [ ] Get a real Canvas feed (Calendar → Calendar Feed) and a real uni timetable feed; record `SUMMARY`, `URL`, `DTSTART` (date vs datetime), `UID` shape.
- [ ] Anonymise them into fixtures (fake course names, no personal links).
- [ ] Adjust the detection rules above to what's really there before Task 2.

### Task 1: Link modules, categories, deadlines and events (data)

**Files:** `venato/blocks/grades.py` (migrate), `venato/store/schema.py`, `venato/store/deadline.py`, `venato/store/outlook.py`, `venato/store/categories.py`, tests `tests/test_grades.py`, `tests/test_deadlines.py`, `tests/test_outlook.py`.

- [ ] `gr_modules.category_id` (nullable). Creating a module creates a timetable category (group "Modules", next free colour) unless one is given; renaming a module renames its category.
- [ ] `deadlines`: add `module_id`, `due_time`, `source` (`'canvas'` / NULL), `uid` (unique when set), and a `deadlines_hidden (uid)` table.
- [ ] `tt_outlook`: add `module_id`. `outlook_category(title)` → the module's category when the event has a `module_id`, else today's default.
- [ ] `goal_hours`: events use their own category (one lookup per event), not one category for all.
- [ ] Tests: module ↔ category created and renamed together; event in a module counts toward that module's hours goal and not the default category's; deleting a module clears links only.

### Task 2: Canvas feed → deadlines; uni timetable → module events

**Files:** Create `venato/feeds.py` (detection + Canvas import); modify `venato/outlook.py` (`check_any_link` recognises `instructure.com` as "Canvas"; `sync` routes Canvas feeds to `feeds.import_canvas` instead of `tt_outlook`); tests `tests/test_feeds.py`.

- [ ] `detect_modules(events) -> [{code, name, sources}]` from both feeds (rules above).
- [ ] `import_canvas(events)`: upsert deadlines by `uid` (title without the bracket, `due`, `due_time`, `module_id` from the course). Skip hidden uids. Don't overwrite `done`, notes or a title the student edited.
- [ ] Sync tags each timetable event with `module_id` by code.
- [ ] Tests with the Task 0 fixtures: modules detected; re-sync idempotent; re-dated assignment moves; ticked/deleted ones stay as the student left them.

### Task 3: New setup wizard

**Files:** `venato/ui/settings_ui.py` (`STEPS`, `wizard`, `_finish`), create `venato/ui/onboarding.py` (the new steps), `tests/test_setup.py`.

Steps: **Welcome → Uni timetable → Canvas → Your modules → Study hours → Your first week → Home**. Every step but Welcome can be skipped.

- [ ] **Uni timetable:** how to find the link (generic steps + "search your uni's site for 'timetable calendar feed'"), paste box, preview "Found N lectures next week".
- [ ] **Canvas:** the 4 steps (Calendar → Calendar Feed → copy), paste box, preview "Found N assignments due".
- [ ] **Your modules:** the detected list (Task 2) with tick/rename/remove, target grade (First / 2:1 / 2:2) once for all, "Add a module" box.
- [ ] **Study hours:** one slider (D6) + per-module override; creates one weekly hours goal per module, counting its category.
- [ ] **Your first week:** suggested sittings for next 7 days on a mini grid (reuse `goal_time.suggestions_for`), **Add to my Plan** / Skip.
- [ ] `_finish`: starter blocks, assistant off, `wizard_done`. Assistant and microphone steps removed (still in Settings → Assistant).
- [ ] Tests: skipping everything still lands on Home; with fixture feeds the student ends with modules, categories, deadlines, goals and planned blocks.

### Task 4: Modules page

**Files:** `venato/ui/grades.py` (becomes the Modules page: list + one module), `venato/blocks/grades.py` (page name per D1), tests `tests/test_grades.py`.

- [ ] List: each module with its colour, next deadline, hours this week (done / planned / goal), current mark vs target.
- [ ] One module: this week's lectures (events), upcoming deadlines (with Plan, Task 5), assessments with marks and "you need X% on the rest", hours planned vs done this week and this term, its timetable blocks, "Fit time" for it.
- [ ] Clicking a deadline or lecture anywhere (Home, timetable) can open its module.

### Task 5: Plan a deadline

**Files:** `venato/ui/deadlines.py` (replace "Make time" with **Plan**), `venato/store/goals.py` (`deadline_id` on goals), `venato/ui/goal_time.py`, tests `tests/test_deadlines.py`, `tests/test_goal_time_app.py`.

- [ ] **Plan** dialog: "Total hours before it's due" **or** "Hours a week", the module (pre-filled), a "finish by" day (default the day before).
- [ ] Saving makes an hours goal: target = total (or hours/week × weeks left), due = finish-by day, counting the module's category with the deadline's title as label. The existing goal machinery then gives suggested sittings, pace, carry-over of missed hours and the "can't make it" offers.
- [ ] The deadline row shows its plan: "6 / 15 h · on track".
- [ ] Deadline done or deleted → its goal closes (Review Focus 5). Re-dated by Canvas → goal due moves.
- [ ] Tests: per-week maths; missed sitting carried into next week's suggestions; done closes the goal.

### Task 6: Focused Home and "More blocks"

**Files:** `venato/ui/home.py`, `venato/ui/goal_time.py` (`needs_you`), `venato/blocks/__init__.py` (`Block.core: bool`), `venato/ui/blocks_ui.py`, `venato/ui/search.py`, `app.py` (sidebar search), tests `tests/test_blocks.py`, `tests/test_chat_app.py`.

- [ ] Home = today's timetable | end-of-day prompt, Ask (if on), **Needs you**, today's to-dos. Nothing else.
- [ ] **Needs you** gathers: goals behind or short, deadlines in the next 7 days with no plan or behind on it, unconfirmed past days, the one-time assistant card (D5). Empty = "Nothing needs you. Go touch grass."
- [ ] Block widgets leave Home (`Block.home` → optional `needs` hook returning Needs-you items).
- [ ] `Block.core`: Timetable, Goals, Focus, Grades/Modules, Review are core. Settings → Blocks shows core first; the rest in a collapsed **More blocks** (D7).
- [ ] Search moves to the sidebar (D4).
- [ ] Tests: Home draws none of the removed widgets; settings with optional blocks on still loads; More blocks collapsed by default.

### Task 7: Docs, merge

- [ ] README: features + "Getting started" for the new setup; CHANGELOG entry.
- [ ] Full test run; push branch; merge to public main; merge public into `venato-private` main (keep private blocks' `core=False`).
