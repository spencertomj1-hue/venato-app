# Blank slate + goal-led onboarding: plan

Generic feature, so it's built in `venato-app` first and then merged into `venato-private`.

## Goal
A new user starts with **nothing preset**. Onboarding asks for their goals (3 months, 6 months, 1 year),
then asks "what would you track to get there?", and *that* fills the app: timetable categories,
sleep/water tracking, habits, blocks and the Home layout. Examples are offered as tickable suggestions, never pre-ticked.

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

## Existing installs
No special treatment: the blank-slate rules apply to everyone. Data is never deleted (the owner's own Mac is an existing
install). Seeding happens only when a database is created, so someone who deletes every category doesn't get them back.

## Phase 1: no presets
1. Remove the seeding of `DEFAULT_CATEGORIES` and `DEFAULT_LABEL_MAP` on new databases. Keep the lists, renamed `EXAMPLE_CATEGORIES`, for suggestions only.
2. Handle zero categories wherever one is assumed: `outlook_category()` (falls back to "no category" → events show grey), focus `_maybe_timetable`, timetable add-block, goal-hours pickers, stats charts. Each one gets an empty state that says "Add a category" and links to it.
3. Workouts/Cut down: stop auto-seeding on new installs. Their empty states offer "Add examples" (a one-click import of the old starter list) next to "Add your own".
4. `blocks.STARTER` → `[]` for new installs. Blocks get picked in onboarding (Phase 4).
5. Tests: a fresh database has 0 categories / 0 label defaults / 0 exercises, and every page renders without errors.

## Phase 2: Daily Log becomes a journal
The Daily Log turns into a **journal** that can also track **sleep** and **water**. Mood, energy and productivity are removed.
1. Sleep and water are optional: switches in Settings → Daily Log (and in onboarding), both **off** on new installs. Off = hidden everywhere.
2. Remove mood, energy and productivity from: the form and calendar (`ui/daily_log.py`, `components/calendar_component.js`), stats and charts
   (`store/stats.py`, `ui/stats.py`), the weekly review (`review.py`, `ui/review.py`), the assistant (`tools/daily_log.py`, `assistant.py`, `quick.py`),
   CSV import/export (`store/history.py`), `store/journal.py`, the wizard (`ui/settings_ui.py`) and the block blurb (`blocks/core.py`).
3. Database: leave the old `mood`/`energy`/`productivity` columns where they are, unread. No migration, so nothing can be lost, and old data stays in the
   file if it's ever wanted. New writes don't touch them.
4. The page leads with the journal box (today's prompt). Sleep and water (if on) sit beside it as two small inputs. The calendar shows which days
   have an entry, plus sleep/water if on. Habits stay on this page.
5. Tests: the form saves notes/sleep/water. No mood/energy/productivity anywhere in the UI, the tools or the CSV. Sleep/water switches hide them.

## Phase 3: Home you arrange yourself
1. Split Home into **widgets**, separate from blocks: `timetable_today`, `ask`, `needs_you`, `todos`, `deadlines`, `goals`, `habits`, `daily_log`, `focus`, plus each other block's existing `home`. Each block declares a list of widgets (`Block.widgets`) instead of just one `home`.
2. **Fully customisable grid.** The layout is a list of rows. Each row holds 1-4 widgets, and each widget has a width
   (¼, ⅓, ½, ⅔, ¾ or full, on a 12-column grid via `st.columns` ratios). Saved in `settings.json` as
   `home: [[{"w": "todos", "span": 6}, {"w": "deadlines", "span": 6}], [{"w": "timetable_today", "span": 12}], ...]`.
   Any widget can go anywhere, timetable and Ask included. Nothing is pinned. Missing key = a default layout.
3. Arranging happens **on Home itself**: a small "Arrange" icon button (`:material/dashboard_customize:`, tertiary) in Home's top-right corner. Clicking it switches Home into arrange mode:
   - Each widget gets a slim bar on top: ↑ / ↓ (move to the row above or below), ← / → (swap within the row), width − / +, and ✕ (hide).
   - "+ Add widget" opens a picker of hidden or unplaced widgets. A new widget goes in a new row, or into a chosen row if it fits.
   - "Done" and "Reset" buttons replace the Arrange button. Changes save straight to `settings.json` (with undo via `venato/undo.py`).
   - Widgets keep showing their real content while you arrange, so you can see what you're moving.
   - No drag-and-drop: Streamlit can't drag its own native widgets around. A JS grid would mean rebuilding every widget in JS. Buttons get the same result.
   - There's no Settings → Home page. Arranging lives on Home only.
4. `ui/home.py` draws from the layout, keeping the per-widget try/except and the fragment behaviour.
5. Tests: a custom grid renders the right rows and widths. An unknown or disabled widget gets skipped. A row whose spans add up to more than 12 gets clamped.

## Phase 4: goal-led onboarding
New wizard: **Welcome → Your goals → What would you track? → Your day (categories) → Journal & habits → Home → Assistant / Calendar / Mic → Done**
(Assistant moves later so the core flow works without AI. If AI is on, it powers the suggestions.)

1. **Your goals**: three boxes, *3 months / 6 months / 1 year*. Each one takes free text plus an optional number target ("Run a half marathon", "Save £2,000"). Saved as goals with `due` = today + 3/6/12 months (the goals table already has `due`).
2. **What would you track to get there?**: for each goal, the user writes or picks what they'd measure. Suggestions come from:
   - AI on: Claude proposes habits, sleep/water tracking, categories and blocks for each goal (one tool call returning JSON). The user ticks which to keep.
   - AI off: a keyword map (e.g. run/gym → Workouts block, Exercise category, "Trained" habit; save/money → Money block; exam/degree → Grades, Study category).
   Everything is **unticked by default**, labelled "examples: pick what you want". Ticked items link to the goal (`habit_id` / `category_id` when the goal is measured that way).
3. **Your day**: build timetable categories. Shows the categories implied by step 2, plus `EXAMPLE_CATEGORIES` as chips, plus "Add your own" (name + colour).
4. **Journal & habits**: switches for tracking sleep and water. Habits use the same chip pattern (examples, unticked, plus add your own).
5. **Home**: Home gets prefilled from what they picked. The last screen points at the Arrange button.
6. Every step can be skipped. "Skip setup" leaves a truly blank app with clear empty states.
7. Re-run from Settings ("Run setup again"). This *adds* things and never deletes.
8. Later: the weekly review asks "still on track for your 3-month goal?" (separate task, not this plan).

## Order and sizing
Phase 1 (small) → Phase 3 (medium) → Phase 2 (medium: removal across many files) → Phase 4 (medium, depends on 1-3).
Each phase is its own PR on `venato-app`, then gets merged into `venato-private`.
