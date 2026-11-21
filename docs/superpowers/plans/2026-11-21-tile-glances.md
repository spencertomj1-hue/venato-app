# Home tiles: whole-day timetable, a stopwatch, and small glances

Spec: the conversation of 2026-11-21. Small graphics on Home tiles that are directly useful and don't crowd
them. Home is one screen and the tiles clip (home.py), so every graphic has a fixed small height.

## Scope (settled)

| # | Tile | Change |
|---|---|---|
| T | Timetable | Shows the **whole day** (the configured day, default 07:00–01:00, 36 rows) with no scrolling. New Home size **Column** (1 wide × every row of Home); Timetable starts in it. Rows fill the height (~20px at a 900px window); a block shows its label when it's tall enough, colour only when it isn't; the time line under the label only when there's room for both. |
| F | Focus | The Home tile becomes a **stopwatch**: a small "What are you on?" box and a start button; tap again to stop. Stopping puts it in today's **Actual** timetable (what the stopwatch already does via `focus.stop`). Pomodoro leaves the tile (stays on the Focus page). While running: the name, the elapsed time, Stop. |
| D | Deadlines | Each row's countdown becomes a coloured pill: red overdue / today, amber within 3 days, grey later. |
| J | Journal | 7 dots, week start first, filled on days written; "3-day streak" when 2 or more. |
| R | Review | Day letters under the bars and a faint 100% line, so an empty week still reads as a chart. |
| H | Daily log | A streak count after each habit's name ("Exercise · 5"). |
| M | Modules (was "Grades") | The Modules block's tile, which setup adds for every student. Grade tracking is binned for now, so it's renamed **Modules** and shows this week's study hours per module: a thin bar per module, done (Actual) against its hours-a-week target (`grades.module_hours`), up to 3 then "and N more". Header: "4 of 12 h this week". |

Default Home (never arranged): Timetable (Column) down the left; To-dos, Focus; Goals, Review; Daily log,
Needs you. Students also get Modules, which spills into a 4th row (user's call: all rows get shorter rather
than dropping a tile).

Not changing: marks/grades UI, Goals, To-dos, Needs you, Ask.

## Phases (risk first)

### Phase 1: the Column size (Size: S)
Verified when: `pytest tests/test_home_layout.py` passes with new cases.
- Acceptance: `home_layout` knows a size `"column"` (1 column, spans every row the layout has, at least 2);
  `place` / `rows` handle it; Edit Home's size picker lists it as "Column"; old saved layouts unchanged.
  Timetable's widget offers it and defaults to it (only for layouts that never saved a size: a saved
  Tall stays Tall).
- Files: `venato/home_layout.py`, `venato/blocks/core.py`, `venato/ui/home.py` (the CSS grid-row span),
  `tests/test_home_layout.py`.
- Blocked by: none.

### Phase 2: timetable fits the whole day (Size: S)
Verified when: the Playwright check below shows 07:00 to 01:00 in the tile, no scrollbar, at 1440×900 and
1280×720; at Tall too (rows just get smaller, min 8px).
- Acceptance: `fitHome` sizes rows as (tile height − header) / SLOTS, min 8px, no scroll; drops the
  HOME_HOURS window and the scroll-to-now; narrow windows (Home scrolls) keep a fixed 18px row.
  Labels hide under ~2 rows of height, the time line under ~3.
- Files: `venato/ui/components/timetable_component.js`, `timetable_component.css`.
- Blocked by: 1.

### Phase 3: Focus stopwatch tile (Size: S)
Verified when: `pytest tests/test_focus.py` passes: start from Home makes a stopwatch session (minutes
None) with the typed name; stop logs a block in today's Actual; the tile has no Pomodoro button.
- Files: `venato/ui/focus.py` (`render_home`, a compact start form), `tests/test_focus.py`.
- Empty name: "Focus".
- Blocked by: none.

### Phase 4: small glances (Size: S)
Verified when: unit tests for the new data (journal week, habit streak) and each tile's render pass.
- Files: `venato/ui/glance.py` (new: `dots(flags, label)`, `pill(text, tone)`), `venato/tile_status.py`
  (`journal_week(today)`), `venato/ui/deadlines.py`, `venato/ui/daily_log.py`, `venato/ui/stats.py`,
  `tests/test_tile_glance.py` (new) and the existing tile tests.
- Streak: reuse the Daily Log page's streak function (no new rule).
- Modules: `venato/ui/grades.py` `render_home`, `tile_status.modules`, the widget's name in
  `venato/blocks/grades.py`; tests in `tests/test_grades.py`.
- Blocked by: none.

### Phase 5: fit check and docs (Size: S)
Verified when: Playwright screenshots on `scripts/seed_demo.py` data at 1440×900 and 1280×720 show no
cut-off graphic or label, light and dark; the full suite passes
(`.venv/bin/python -m pytest -q -p no:logging tests`).
- Files: `assets/home.png`, `HANDOVER.md`, `CHANGELOG.md`, home.py's top docstring (sizes).
- Blocked by: 2, 3, 4.

## Decision log
| Decision | Chosen | Why |
|---|---|---|
| Timetable height | new Column size (1 × all rows) | Tall gives ~13px rows: labels don't fit |
| Stopwatch name | typed before starting ("Focus" if empty) | user's call |
| Pomodoro on Home | removed, stays on the Focus page | simplest tile |
| Grades tile | renamed Modules, shows study hours per module, not marks | grade tracking is binned for now (onboarding v2); hours are what setup collects |
| Students' extra tile | allowed: Home grows to 4 rows | user's call |
| Column's height | fixed 3 rows (Home's default height), not "every row" | a span that depends on the row count is circular; 3 is the one-screen default |
| How to draw | inline HTML/CSS via `st.html` (as Review and Goals already do) | no new library, theme tokens |
| Home's minimum row | 8px (was 10px), plus the header trim above | a student's 4-row Home at 1280×720 fits the whole day |
| Home's MIN_ROW | 108px (was 132) | a student's 4-row Home fits one screen at 1280×720 |
| Animation | none, bar the existing now-line and the running stopwatch | a screen of moving tiles is noise |

## Not yet specified
- Nothing.

## Always / Never
- Always: fixed height for every glance, an `aria-label` saying the same in words, light and dark, tests.
- Never: a chart library, new tables, marks/grades UI, Goals / To-dos / Needs you changes, a graphic that grows a tile.

## Progress
| Phase | Status |
| --- | --- |
| 1 Column size | done |
| 2 Whole-day timetable | done |
| 3 Stopwatch tile | done |
| 4 Glances | done |
| 5 Fit check, docs | done (see Phase 5 note) |

### Phase 2 note (measured on seed_demo data, Playwright)
First build (Column 3 rows, 10px minimum) didn't fit: a 3-row Home at 1280×720 was 6px short, a student's
4-row Home at 1280×720 78px short. User's call: trim the tile's fixed costs and let rows go to 8px. The sync
and Outlook buttons now sit in the tile's title line (Outlook as an icon), the day header row goes when it has
no all-day chip or state. After:
| Home | Window | Row | Fits 07:00–01:00? |
|---|---|---|---|
| 3 rows | 1440×900 | 16px | yes |
| 3 rows | 1280×720 | 11px | yes |
| 4 rows (student) | 1440×900 | 11px | yes |
| 4 rows (student) | 1280×720 | 9px | yes |

### Phase 5 note (Playwright, seed_demo data, 1440×900 and 1280×720, light and dark)
- Fixed on the way: the Timetable title was squeezed by its status (the status now gives way); Focus had an empty
  slot above its form and a two-line running view (now one line); Review's letters were cut at 114px rows (shorter
  bars on short windows, the % moved to the header); Journal's Write and Deadlines' See all took a line on Home
  (hidden, as Goals' and Habits' already were).
- Still clipped at 1280×720 (rows 114px), by Home's clip-rather-than-grow rule, in tiles this plan doesn't change:
  To-dos' "New to-do" and Goals' second bar are cut mid-line; Daily log's second row of habits is hidden whole.
  Deadlines (when added) shows its first row and part of the second. At 1440×900 everything fits.
