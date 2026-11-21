# Onboarding v2: fewer steps, nothing lost, a first week that's never empty

Builds on `2026-11-20-blank-slate-student-onboarding.md`. Its decisions stand unless the Decision log below overrides
one (D6 and the 3/6/12 goal slots are up for change, see "Open questions").

**Goal:** Setup takes about 3 minutes, never loses what someone typed, and always ends on a filled first week.

**Now:** 11 steps (student) / 7 (not). **After:** 6 / 4.

```
Welcome + "Are you at uni?" -> (uni: Connect calendars -> Modules & study hours)
  -> Goals -> What to track -> Your first week -> Home
```

## Global constraints

- Setup only adds. Running it again deletes nothing (`test_running_setup_again_deletes_nothing` stays green).
- Every step but Welcome can be skipped. Skipping everything still gives a blank Home.
- Calendar links stay in the system secret store.
- Short, plain, British copy. WCAG AA in light and dark.
- Tests: `.venv/bin/python -m pytest -q -p no:logging tests` (main seam: `tests/test_setup.py`, AppTest on `app.py`).
- Screens checked with a Playwright walk-through at 1280×900 and 390×844, light and dark.

## Phases

### Phase 1: Bugs and footer (no change to the steps)
Verified when: every bug from the review has a failing-then-passing test in `tests/test_setup.py`.
Files: `venato/ui/onboarding.py`, `tests/test_setup.py`.

#### Step 1.1: Next saves what's typed (S)
- Pressing Next with a link in the box connects it (the same as Connect). An error keeps you on the step.
- Next adds a typed module name, own habit or own category, as if you'd pressed Add.
- Verify: new tests `test_next_connects_a_pasted_link`, `test_next_keeps_a_typed_module_habit_and_category`.
- Blocked by: none.

#### Step 1.2: One action button, honest copy (XS)
- The footer has Back on the left and one main button on the right. It says **Skip** while the step is empty and
  **Next** once something is filled in (or something has been connected or ticked).
- "About two minutes" becomes "A few minutes". "Arrange" becomes "Edit Home".
- Verify: existing skip tests adapted (`wiz_skip` key kept for the empty state).
- Blocked by: 1.1.

#### Step 1.3: The student question can't be skipped by accident (XS)
- Two big buttons, "I'm at uni" and "Not a student", that move on when pressed. No radio, no Next.
- Verify: `test_a_non_student_gets_no_uni_steps` and `test_a_student_gets_the_uni_steps_and_modules` updated to
  press the cards.
- Blocked by: none.

### Phase 2: Fewer steps
Verified when: the student path is 6 steps, the non-student path is 4, and the fixture test
`test_student_with_the_fixture_feeds_ends_up_with_everything` still ends with the same data.
Files: `venato/ui/onboarding.py`, `venato/ui/settings_ui.py`, `tests/test_setup.py`.

#### Step 2.1: Welcome asks the student question (S)
- Welcome shows the two cards from 1.3 instead of "Get started". "Skip setup" stays.
- The step count is known from the first screen, so the counter never jumps. The caption shows the step names
  ("Calendars · Modules · Goals · Track · First week") with the current one highlighted, not "step 3 of 11".
- Blocked by: 1.3.

#### Step 2.2: One "Connect calendars" step (M)
- Timetable and Canvas sit on one screen as two cards, each with its own box and Connect button, each optional.
- The link box is plain text (not hidden), so people can check what they pasted.
- Under the Outlook guide, a "Not using Outlook?" expander explains how to get an .ics link from Google Calendar or a
  uni timetable portal.
- Verify: the fixture test connects both on one step.
- Blocked by: 1.1.

#### Step 2.3: Modules and study hours on one step (M)
- Study hours move into the Modules step as one number box per module, starting at 6 h (D6, Q2).
- A line under them adds them up: "4 modules · 32 h a week, lectures included".
- Credits leave setup (the default is 15, changed on the Modules page). Target grade stays as one segmented control.
- `apply_study_hours` uses each module's own number (`gr.set_week_hours_goal`) where it differs from the default.
- Verify: `test_study_goals_respect_a_modules_own_hours` and `test_study_hours_leave_old_modules_alone` still pass,
  plus a new test that changing one module's box gives just that module a different goal.
- Blocked by: 2.2.

#### Step 2.4: "What to track" merges in "Your day" (M)
- One step. At the top are the suggestions for each goal, as now.
- Below that, every example category is shown as a coloured chip you tap to switch on (chips already switched on by a
  suggestion show as on). There's no "(Life)" or "(Work)" text after the names.
- "Add your own" asks for a name and a colour. The group defaults to the category group with the fewest entries
  (normally Life). Groups are set in Settings, not in setup.
- `_save_day` is folded into `_save_track`.
- Verify: `test_tracking_suggestions_link_and_switch`, plus a new test that a chip switched on in setup creates its
  category with the activity names that default to it.
- Blocked by: 1.1.

#### Step 2.5: No Home step (S)
- `_finish` adds every widget from `home_picks()` automatically. The last step (First week) has the
  "Start using Venato" button, and a caption mentions Edit Home.
- Verify: a new test checks that finishing with a goal and a habit puts Goals and Habits on Home.
- Blocked by: none.

### Phase 3: Goals and a first week that's never empty
Verified when: a non-student who types one goal with no number still sees sessions on "Your first week".
Files: `venato/ui/onboarding.py`, `venato/suggest.py` (maybe), `tests/test_setup.py`.

#### Step 3.1: Goal rows (M)
- Each goal row has: what (text), **by when** (chips: 1 month, 3 months, 6 months, 1 year; 3 months selected), and
  **how you'll track it** (chips: Tick it off / Hours a week / A number). Picking Hours a week or A number shows a box.
- Starts with one row. "+ Add another goal" adds up to 5.
- Placeholders differ from row to row ("e.g. Run a 10k", "e.g. Read 12 books", "e.g. Get a 2:1").
- Hours a week becomes an hours goal (`unit="h"`) over the chosen time. A number becomes a numeric target. Tick it
  off is a target of 1, as now.
- `save_goals` keeps its update-in-place behaviour (`test_goals_save_once_and_update_in_place`).
- Blocked by: 2.1.

#### Step 3.2: First week fallback (S)
- When `first_week()` finds nothing, suggest 3 × 1 h sittings in free time for each goal with no hours (Q3), labelled with the goal, so the screen is never empty. They're only added if Add to my Plan is pressed.
- Verify: new test `test_first_week_is_never_empty_with_a_goal`.
- Blocked by: 3.1.

### Phase 4: Look
Verified when: the Playwright walk-through screenshots pass a visual check in light and dark, at both widths.
Files: `venato/ui/onboarding.py`, `assets/` (onboarding image).

#### Step 4.1: Welcome shows the app (S)
- The bullet list becomes a short line plus `assets/timetable.png` (plan vs actual), with the privacy line kept.
- Blocked by: 2.1.

#### Step 4.2: Layout polish (S)
- The progress bar uses a neutral ink colour, not the brand red (red means error).
- The card is centred vertically when it's shorter than the window. Empty-state captions get normal-size text.
- Blocked by: 1.2.

## Decision log

| Decision | Chosen option | Why |
| --- | --- | --- |
| Next saves pending input | Yes, on every step | Typed-then-Next is what people do; losing it silently is the worst bug |
| Student question | Cards on Welcome | Removes a step and stops the counter jumping |
| Credits in setup | Removed | Only matters for the weighted average; Modules page has it |
| Groups in setup | Hidden | Power-user concept; a default group is fine |
| Home step | Removed, widgets added automatically | Nobody knows what they want on a dashboard they haven't seen |
| Goals shape | Free rows + by when + unit | Q1 |
| Study hours | Flat 6 h, per-module boxes | Q2, keeps D6 |
| First-week fallback | 3 × 1 h a week per goal | Q3 |
| Shipping | 4 PRs, one per phase | Q4 |
| Link box | Visible text | It's a link, not a password; people need to check the paste |

## Questions (answered)

All answered 2026-11-21:

- Q1: Goals: free rows with "by when" and "how you'll track it", replacing the 3/6/12 slots. **Yes.**
- Q2: Study hours default: **keep D6, a flat 6 h a module**, editable per module, with the weekly total shown.
- Q3: First-week fallback: **3 × 1 h sittings a week, in free time, for each goal with no hours.**
- Q4: **4 PRs, one per phase**, in order.

## Not yet specified

- Phase 2.2: the non-Outlook guide's wording needs a real Google Calendar and portal check; written at pickup.
- Phase 4.1: whether `assets/timetable.png` reads well at 390 px; may need a cropped image.

## Always / Never

- Always: tests for every behaviour change; British copy; the skip-everything path stays blank.
- Never: AI in setup (D5); deleting or rewriting existing data; asking for anything the app can work out itself;
  new blocks or widgets.

## Progress

| Phase | Status |
| --- | --- |
| 1 Bugs and footer | Not started |
| 2 Fewer steps | Not started |
| 3 Goals and first week | Not started |
| 4 Look | Not started |
