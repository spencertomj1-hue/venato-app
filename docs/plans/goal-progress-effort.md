# Plan: effort-weighted goal progress, with qualitative targets

## The model

```
Goal (3/6/12 months)
 ├─ Target (by a date)  ── effort 1–10
 │    └─ To-dos         ── effort 1–10
 └─ To-dos for the goal ── effort 1–10
Standalone to-dos (no goal, no target) stay as they are and count for nothing above them.
```

## Effort

- Every target and to-do gets an **effort 1–10**: how big a chunk of the goal it is (hard × long).
- Picker: three quick chips, **Small 2 · Medium 5 · Big 8**, plus a 1–10 slider under "Exact".
  Default 5, so leaving it alone is fine.
- Shown on rows as a small `●●●○○` (effort ÷ 2), with the number in its tooltip.

## Two kinds of target

| Kind | Example | Progress (0–1) |
|---|---|---|
| **Number** (exists today: by hand, from a habit, from timetable hours) | 50 users | value ÷ target |
| **Milestone** (new, qualitative) | "Launch on the App Store" | its to-dos' effort done ÷ their total effort; with no to-dos, 0 or 1 (a tick) |

- A milestone can also have an optional **"How far, honestly?"** slider (0–100%) for fuzzy stuff
  ("get good at Swift"). When set it replaces the to-do calculation, and its row says "self-rated".
- A number target's to-dos are how you get there. They don't add to its %, so nothing counts twice.
  (Ticking one still offers +1, as it does now.)

## Goal %

```
goal % = Σ (effort × progress) over the goal's targets and its own to-dos
         ─────────────────────────────────────────────────────────────────
                       Σ effort over the same
```

- A goal-level to-do counts as a tiny milestone: 0 or 1, at its effort.
- Pace tick: number targets keep `pace.expected`. A milestone's expected value is the share of time
  gone between its start and due date. The goal's expected value is the same weighted mean.
- The header's tooltip breaks it down, e.g. "Users 0% (effort 8) · Apple licence 100% (3) · …".

## Schema (additive only, `_add_column`)

- `goals.effort INTEGER` and `todos.effort INTEGER`: NULL is read as 5.
- `goals.milestone INTEGER NOT NULL DEFAULT 0`: 1 = milestone (its `target` is 1, `progress` 0 or 1).
- `goals.self_rating REAL`: NULL means not used.
- Existing goals keep their % until you set efforts. Exception: goal-level to-dos start counting,
  so goals with both targets and to-dos will move a bit. Say so in the changelog.

## Code

1. `store/life_goals.py`: `life_goal_progress` becomes the weighted sum. Add `target_progress(t)`
   (number / milestone / self-rated) and `effort(x)`. Home's tile, the weekly review and the assistant
   already call it, so they all follow.
2. `ui/life_goals.expected_fraction`: the same weighting.
3. `ui/goals._goal_form`: a "Number / Milestone" switch; the effort picker; a milestone hides
   unit, amount and source.
4. To-do forms (goal card, target row, To-dos page pop-up): the effort chips.
5. `ui/goals._goal_row`: a milestone row shows "3 of 5 steps · 60%" and a tick box instead of − / +.
6. Assistant tools (`assistant.py` `add_goal` / `add_todo`): optional `effort`, and `milestone` for targets.
7. Export/import (`load_goals` / `save_goals`, to-dos): the new columns.

## Tests

- Weighted % maths: equal efforts match today's mean; an effort-8 target outweighs an effort-2 one;
  NULL is read as 5.
- A milestone: % from its to-dos' effort; a tick with none; a self-rating overrides both.
- Ticking a milestone's last to-do: the milestone shows done and the goal % moves.
- Migration: an old database opens, every row's effort is NULL, and the numbers are the same for
  goals with no to-dos.
- Expected (pace) value for a milestone halfway through its span is 0.5.

## Decisions made

- Goal-level to-dos count toward the goal % (at their effort), even when the goal has targets.
- Effort NULL means 5. No backfill.
- Standalone to-dos get the effort field too (it's on the To-dos pop-up) but feed no bar.

## Cleanup to fold into phase 1

- `venato/pace.py` `suggestions`, `suggested_target`, `dismiss_suggestion`, and their tests in `tests/test_pace.py`:
  nothing in the UI calls them any more (the Goals page side panel was removed). Check with grep, then delete.
- `venato/ui/goal_time.py` `GOAL_COLOURS` (and its comment): unused since `free_split` went. Check, then delete.

## Order

1. Store and maths, with tests (no UI).
2. Milestone targets in the form and row.
3. Effort picker on targets and to-dos.
4. Breakdown tooltip, assistant, export.
