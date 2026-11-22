# Goals become central: long-term goals with targets and to-dos

Spec: the conversation of 2026-11-22. A **Goal** is an overarching plan over 3, 6 or 12 months ("Get fit",
"Land a grad job"). Under each goal sit **targets** (measurable, by a date: "Gym 40 sessions by 31/03") and
**to-dos** ("Update CV"). Today's goals and to-do system fold into this; every existing mechanic keeps working.

## What exists today (research)

- `goals` table = measurable target with a deadline: hand count / habit ticks / timetable hours
  (`store/goals.py`), pace + charts (`pace.py`, `ui/goal_chart.py`), weekly free-time split (`goal_week`,
  `ui/goal_time.py`), deadline plans (`goals.deadline_id`, `closed`).
- **Every goal is already a to-do category**: `todo_groups.goal_id` (`link_goal_group`, `rename_goal_group`).
  So "to-dos under a goal" already half-exists, one level too low.
- To-dos: daily/weekly/monthly lists, repeat/rollover, due day, minutes, category, timetable scheduling
  (`store/todos.py`, `ui/todos.py` + JS component).
- Assistant tools: `tools/goals.py`, `tools/todos.py`, `tools/goal_time.py`.
- **Since PR #38 (merged 2026-11-22):** Timetable's "Give it time" side panel (`ui/timetable_side.py`) lists
  open to-dos and non-habit goals flat; pick one, drag on the week to place it. `tt_links` (`store/links.py`,
  `kind IN ('goal')`, `ref` = `goals.id`) makes a hand-counted target go up one when its block is marked
  done. Home tiles now resize by a corner grip (`home_flip.js`), so a tile's content must fit any size it offers.

## Model

| Concept (UI word) | Storage | Notes |
|---|---|---|
| **Goal** (new) | new table `life_goals` (id, title, why, horizon 3/6/12, start, end, ord, created_at, archived) | end = start + horizon months; editable |
| **Target** (today's "goal") | existing `goals` table, + column `life_goal_id` (nullable) | all pace/hours/habit/deadline-plan mechanics unchanged |
| **To-do** | existing `todos` | joined to a Goal through its `todo_group` (new column `todo_groups.life_goal_id`) |

Table stays `goals` for targets: renaming it touches every query, export/import CSV and the assistant;
the UI rename is free. Internally: `life_goal` = Goal, `goal` = target.

## Phases (risk first)

### Phase 1: schema + store (Size: M)
Verified when: `pytest tests/test_life_goals.py tests/test_goals.py tests/test_todos.py tests/test_store.py` green.
- Acceptance: migration adds `life_goals`, `goals.life_goal_id`, `todo_groups.life_goal_id`, idempotent on
  old DBs (backup first, like `_goals_became_todos`); `store/life_goals.py` add/update/delete/reorder/list
  (active, past), each with its targets, its to-do group, and progress = mean of its targets' fractions
  (to-dos done/total when it has no targets); creating a Goal creates its to-do group; deleting one
  unlinks (targets and to-dos survive, like `delete_goal`).
- Existing targets: `life_goal_id` NULL (D2).
- Export/import: `load_life_goals` / `save_life_goals`; targets' CSV gains `life_goal` (by title).
- Files: `venato/store/schema.py`, `venato/store/life_goals.py` (new), `venato/store/goals.py`,
  `venato/store/todos.py`, `venato/store/__init__.py`, `venato/facade.py`, `tests/test_life_goals.py` (new).
- Blocked by: none.

### Phase 2: Goals page becomes the hub (Size: M)
Verified when: `pytest tests/test_goal_time_app.py tests/test_life_goals_app.py` green + Playwright screenshot.
- Acceptance: page lists Goals as cards (title, horizon, time left, overall bar); a card opens to its
  targets (today's `_goal_row`, unchanged) and its to-dos (add/tick inline, same store calls as To-dos page);
  "New goal" (title, why, 3/6/12) and "Add target" (today's form, Goal preselected); targets with no Goal
  under "Not under a goal"; side panel (free-time split, offers, suggestions) and Deadlines unchanged.
- Files: `venato/ui/goals.py`, `venato/ui/life_goals.py` (new), `tests/test_life_goals_app.py` (new).
- Blocked by: 1.

### Phase 3: To-dos page + Home (Size: S)
Verified when: `pytest tests/test_todos_app.py tests/test_home_layout.py tests/test_tile_glance.py` green.
- Acceptance: To-do category picker shows Goal groups first with a flag; "By category" view groups under
  Goals; Home Goals tile shows Goals (overall bar each, nearest target under it) per D4.
- Files: `venato/ui/todos.py`, `venato/ui/components/todos_component.js`, `venato/ui/goals.py`
  (`render_home`), `venato/blocks/core.py`.
- Blocked by: 2.

### Phase 3b: Timetable side panel by Goal (Size: S)
Verified when: `pytest tests/test_timetable_side.py tests/test_timetable_todo_sync.py` green + screenshot.
- Acceptance: "Give it time" groups its to-dos and targets under a heading per Goal (active Goals in order),
  then "Other to-dos" / "Other targets"; picking, placing, `tt_links` and done-counting unchanged; a Goal
  itself is a heading, never pickable (time goes to its targets / to-dos).
- Home Goals tile (Phase 3) checked at every size its widget offers, now that the grip resizes tiles.
- Files: `venato/ui/timetable_side.py`, `tests/test_timetable_side.py`.
- Blocked by: 1 (can run alongside 2).

### Phase 4: assistant tools (Size: S)
Verified when: `pytest tests/test_tools.py tests/test_assistant_session.py` green.
- Acceptance: `add_life_goal`, `list_life_goals`, `edit_life_goal`; `add_goal` (target) and `add_todo` take
  optional `life_goal`; tool descriptions use Goal / target words.
- Files: `venato/tools/life_goals.py` (new), `venato/tools/goals.py`, `venato/tools/todos.py`,
  `venato/tools/__init__.py`.
- Blocked by: 1.

### Phase 5: wording + docs (Size: S)
Verified when: full `pytest` green; `grep` shows no user-facing "goal" meaning target.
- Acceptance: UI copy says "target" for measurable ones (Needs you, pace lines, onboarding, Settings,
  the Timetable side panel and its hint "Pick a to-do or goal");
  README / CHANGELOG / FOR-TOM updated; demo seed (`scripts/seed_demo.py`) has 2 Goals.
- Blocked by: 2, 3, 3b, 4.

## Decision log
| Decision | Chosen | Why |
|---|---|---|
| Keep `goals` table for targets | yes | zero risk to pace/hours/deadline-plan code |
| To-dos join Goals via their category | yes | reuses the existing goal→category link; to-dos keep periods, rollover, scheduling |
| `tt_links` stays `kind = 'goal'` → targets | yes | blocks serve targets; a Goal gets time only through them, so no schema change to the merged table |
| Goal progress | mean of targets' fractions; to-dos if no targets | needs no new input from the user |
| D1 links | a target / to-do sits under at most one Goal | simple; one column each |
| D2 existing data | existing targets stay unparented ("Not under a goal"); user assigns | nothing guessed |
| D3 horizon | 3 / 6 / 12 buttons + custom end date | odd lengths (a term, a season) |
| D4 Home | Goals tile shows one row per Goal (overall bar + nearest target); layout untouched | central without moving saved layouts |

## Not yet specified
- Nothing open: D1–D4 answered 2026-11-22.

## Always / Never
- Always: every current mechanic (habit/hours/hand targets, pace, weekly split, deadline plans, side-panel
  placing and done-counting, tile resizing, to-do
  periods/repeat/rollover/scheduling, undo, export/import) behaves the same.
- Never: drop or rename `goals`/`todos` tables; force every target or to-do under a Goal.

## Progress
| Phase | Status |
|---|---|
| 1 | pending |
| 2 | pending |
| 3 | pending |
| 3b | pending |
| 4 | pending |
| 5 | pending |
