# Setup asks for long-term goals first

Spec: the conversation of 2026-11-22, after `2026-11-22-goals-central.md` shipped. FOR-TOM item 2 ("learn what
people's goals are before anything else"). Setup's goals step still makes **targets**; it should make
**long-term goals** (3 / 6 / 12 months), with a first target and to-do under each, and every later step
(Track, First week, Modules, Home) should hang off them.

## What exists (research, `venato/ui/onboarding.py`)

- Steps: Welcome → (students: Calendars → Modules) → Goals → Track → First week.
- Goals step: up to 5 rows `(text, By when 1/3/6/12 months, How: Tick it off / Hours a week / A number, number)`.
  `save_goals(rows)` makes one **target** per row (tick = target 1; number; hours = h/week × weeks, with a
  category), re-saves idempotently via `ob["goal_ids"][row]`, `forget_goal_row` deletes only its own.
- Track: suggestions per target title (`suggest.for_goal`); `apply_suggestion` links a habit/category to the target.
- First week: `first_week` (hours targets' sittings) + `fallback_sittings` (3 × 1 h for non-hours targets).
- Modules: `apply_study_hours` makes one "<Module> study" hours target per new module (12 weeks), under no goal.
- `home_picks`: offers the Goals tile when `store.goals_open()`.
- Tests: `tests/test_setup.py` (save_goals, Track, First week, home_picks), `tests/test_blank_slate.py`.

## Model per goal row

| Row field | Becomes |
|---|---|
| Goal text | a **long-term goal** (`add_life_goal`) |
| How long: 3 / 6 / 12 months, or an end date | its span from today (D2) |
| Why (optional, folded) | `why` |
| How you'll know: Hours a week / A number | one **target** under it, due on the goal's end (same maths as today) |
| How you'll know: Tick it off | no target (D1) |
| First step (optional) | one **to-do** in the goal's category (this week's list) |

Re-saving updates the same goal / target / to-do (`ob["life_ids"]`, `ob["goal_ids"]`, `ob["todo_ids"]` by row);
emptying a row deletes only what this setup made for it (goal, its target, its to-do).

## Phases (risk first)

### Phase 1: save_goals makes goals (Size: M)
Verified when: `pytest tests/test_setup.py tests/test_blank_slate.py` green with new cases.
- Acceptance: each row makes goal + (target per How) + (to-do if First step); re-save edits in place, switching
  How swaps the target's tracking as today; emptying/removing a row removes only its own three things;
  `_my_goals()` returns `(row, life_goal, target or None)`.
- Files: `venato/ui/onboarding.py`, `tests/test_setup.py`.
- Blocked by: none.

### Phase 2: the Goals step UI (Size: S)
Verified when: AppTest walks setup (new test) + screenshot of the step.
- Acceptance: header "Your goals for the next few months"; per row: goal, How long (3/6/12), How you'll
  know, number, then a folded "Why it matters / First step" pair; copy explains goal vs target in one line;
  step order per D3.
- Files: `venato/ui/onboarding.py`, `venato/ui/settings_ui.py` (wizard step order, if D3 moves it).
- Blocked by: 1.

### Phase 3: Track, Modules, First week, Home follow goals (Size: M)
Verified when: `pytest tests/test_setup.py tests/test_life_goals_app.py` green.
- Acceptance:
  - Track: suggestions grouped under each goal title; a habit picked for a goal **with** a target links to it
    (as today); for a goal **without** one, makes a habit-counted target under the goal (D1).
    "Count it towards" lists goals.
  - Modules (students): per D4.
  - First week: sittings labelled with the target (hours ones) or the goal (fallback), one set per goal.
  - `home_picks`: Goals tile when any long-term goal or target exists.
- Files: `venato/ui/onboarding.py`, `tests/test_setup.py`.
- Blocked by: 1.

### Phase 4: docs (Size: XS)
- README "Everyone" setup paragraph and step list, CHANGELOG, tick FOR-TOM item 2 (partly: questions still
  to be designed with customer discovery).
- Blocked by: 2, 3.

## Decision log
| Decision | Chosen | Why |
|---|---|---|
| Row = goal + first target + first to-do | yes | one screen still; the rest is added on the Goals page |
| Existing setups / re-running setup | only adds, as today | setup never deletes what it didn't make |
| D1 "Tick it off" | just the goal, no target: its bar fills from its to-dos; a habit picked on Track makes a habit-counted target under it | a yes/no target would jump 0→100% and ignore to-dos |
| D2 length | 3 / 6 / 12 months + "Pick an end date" (1 month dropped) | matches the Goals page's form |
| D3 order | Goals right after Welcome, for everyone | FOR-TOM item 2: goals before anything else |
| D4 module study targets | students get a prefilled first row "Do well this term" (3 months, editable, removable); module targets go under it, else under no goal | study time counts towards a goal without extra typing |

## Not yet specified
- Nothing open: D1–D4 answered 2026-11-22.

## Always / Never
- Always: Skip anywhere still works; re-running setup never duplicates; everything is undoable on the Goals page.
- Never: force a target or to-do per goal; change the wizard's calendar / module / colour logic beyond D3–D4.

## Progress
| Phase | Status |
|---|---|
| 1 | done |
| 2 | done |
| 3 | done |
| 4 | pending |
