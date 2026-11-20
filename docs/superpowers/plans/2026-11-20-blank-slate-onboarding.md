# Blank slate + goal-led onboarding: plan

Generic feature, so it's built in `venato-app` first and then merged into `venato-private`.

## Goal
A new user starts with **nothing preset**. Onboarding asks for their goals (3 months, 6 months, 1 year),
then asks "what would you track to get there?", and *that* fills the app: timetable categories,
daily-log fields, habits, blocks and the Home layout. Examples are offered as tickable suggestions, never pre-ticked.

## Today (what changes)
| Area | Now | Where |
|---|---|---|
| Timetable categories | 13 seeded (Sleep, Meals, Classes…) + label map (Gym→exercise…) | `store/categories.py`, `store/schema.py:180-187` |
| Outlook category | defaults to `classes` | `store/categories.py:30` |
| Daily log | fixed columns: mood, sleep, energy, water, productivity | `entries` table, `ui/daily_log.py`, `store/journal.py` |
| Starter blocks | timetable, goals, focus, grades, stats | `blocks/__init__.py:48` |
| Workouts / Cut down | seeded exercise list and trackers | `blocks/workouts.py:23`, `blocks/cutdown.py:18` |
| Home | one widget per block, in block order; "goals" block draws to-dos and deadlines together | `ui/home.py`, `blocks/core.py` |
| Onboarding | Welcome → Assistant → Calendar → Mic → Done. No goals step | `ui/settings_ui.py:224+` |

## Rule for existing installs
Only **new** databases start blank. Existing data (including the owner's) keeps its categories, fields and layout.
The "is new" check is "the database was just created", not "the table is empty", so someone who deletes every category doesn't get them back.

## Phase 1: no presets
1. Remove the seeding of `DEFAULT_CATEGORIES` and `DEFAULT_LABEL_MAP` on new databases. Keep the lists, renamed `EXAMPLE_CATEGORIES`, for suggestions only.
2. Handle zero categories wherever one is assumed: `outlook_category()` (falls back to "no category" → events show grey), focus `_maybe_timetable`, timetable add-block, goal-hours pickers, stats charts. Each one gets an empty state that says "Add a category" and links to it.
3. Workouts/Cut down: stop auto-seeding on new installs. Their empty states offer "Add examples" (a one-click import of the old starter list) next to "Add your own".
4. `blocks.STARTER` → `[]` for new installs. Blocks get picked in onboarding (Phase 4).
5. Tests: a fresh database has 0 categories / 0 label defaults / 0 exercises, and every page renders without errors.

## Phase 2: customisable daily log
1. New table `log_fields(id, name, kind, unit, min, max, ord, on)`. Kinds: `score` (1-10), `number` (with a unit), `yes/no`, `text`.
2. New table `log_values(date, field_id, value)`. Mood, sleep, energy, water and productivity become **built-in example fields**. On existing installs a migration creates them as `log_fields` rows (switched on) and copies the `entries` columns into `log_values`. Keep `entries.notes` for the journal.
3. New installs: no fields switched on. The Daily Log page shows "What do you want to log each day?", with the 5 examples as chips plus "Custom…".
4. Update the form, the calendar component, stats charts, CSV import/export (`store/history.py`), assistant tools/context and the weekly review so they read the field list instead of fixed columns.
5. Settings → Daily Log: add, rename, reorder or switch off fields. Switching a field off hides it but keeps its data.
6. Tests: migration round-trip (old columns → values, identical numbers), a custom field shows in the form, stats and the CSV.

## Phase 3: Home you arrange yourself
1. Split Home into **widgets**, separate from blocks: `timetable_today`, `ask`, `needs_you`, `todos`, `deadlines`, `goals`, `habits`, `daily_log`, `focus`, plus each other block's existing `home`. Each block declares a list of widgets (`Block.widgets`) instead of just one `home`.
2. Save the layout in `settings.json` as `home: {"left": [...], "right": [...]}`. Missing key = today's layout, so existing installs see no change.
3. Settings → Home: two columns of chips. Drag (or ↑/↓) to reorder, move between columns, toggle on and off. Only widgets from switched-on blocks are listed. "Reset to default" button.
4. `ui/home.py` draws from the layout, keeping the per-widget try/except and the fragment behaviour.
5. Tests: a custom layout renders in that order. An unknown or disabled widget gets skipped. The default layout matches the current Home exactly.

## Phase 4: goal-led onboarding
New wizard: **Welcome → Your goals → What would you track? → Your day (categories) → Daily log & habits → Home → Assistant / Calendar / Mic → Done**
(Assistant moves later so the core flow works without AI. If AI is on, it powers the suggestions.)

1. **Your goals**: three boxes, *3 months / 6 months / 1 year*. Each one takes free text plus an optional number target ("Run a half marathon", "Save £2,000"). Saved as goals with `due` = today + 3/6/12 months (the goals table already has `due`).
2. **What would you track to get there?**: for each goal, the user writes or picks what they'd measure. Suggestions come from:
   - AI on: Claude proposes habits, log fields, categories and blocks for each goal (one tool call returning JSON). The user ticks which to keep.
   - AI off: a keyword map (e.g. run/gym → Workouts block, Exercise category, "Trained" habit; save/money → Money block; exam/degree → Grades, Study category).
   Everything is **unticked by default**, labelled "examples: pick what you want". Ticked items link to the goal (`habit_id` / `category_id` when the goal is measured that way).
3. **Your day**: build timetable categories. Shows the categories implied by step 2, plus `EXAMPLE_CATEGORIES` as chips, plus "Add your own" (name + colour).
4. **Daily log & habits**: the same chip pattern for log fields (Phase 2) and habits.
5. **Home**: a preview of the Home layout built from what they picked (Phase 3 editor, prefilled).
6. Every step can be skipped. "Skip setup" leaves a truly blank app with clear empty states.
7. Re-run from Settings ("Run setup again"). This *adds* things and never deletes.
8. Later: the weekly review asks "still on track for your 3-month goal?" (separate task, not this plan).

## Order and sizing
Phase 1 (small) → Phase 3 (medium) → Phase 2 (largest: schema migration) → Phase 4 (medium, depends on 1-3).
Each phase is its own PR on `venato-app`, then gets merged into `venato-private`.

## Open decisions
1. Existing installs stay as they are (proposed above). OK?
2. Daily log custom fields: full migration to `log_fields`/`log_values` (proposed), or the cheaper option: keep the 5 fixed columns, let users switch them off, and only add *new* custom fields in a side table?
3. Home: two fixed columns (proposed), or a free grid?
