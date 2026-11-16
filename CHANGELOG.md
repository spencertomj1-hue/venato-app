# Changelog

All notable changes to Venato are listed here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Versions match the git tags and [GitHub Releases](https://github.com/spencertomj1-hue/venato-app/releases).
Venato was called **Arete** up to 1.1.1.

## [Unreleased]

### Added
- Timetable: one timeline. Plan once; time that has passed shows what happened. A day is assumed to have gone as planned (drawn faded and dashed, with "?") until you confirm it: Confirm under the day, "Confirm week as planned" (with a preview), or Home's end-of-day prompt "Anything not go to plan today?" (All as planned / Review; also for yesterday). Click a passed block for Didn't happen, Change times (or drag its edges) or Did something else; drag across empty passed time to add something unplanned. Skipped blocks are hatched and struck through, unplanned ones outlined, with a text equivalent in the keyboard block list. The side-by-side Plan and Actual view is still there (Settings → Region → Timetable view); new installs start with one timeline, existing ones keep two columns until they switch.
- Timetable: suggested sittings. When hours goals are short this week, the grid draws where Plan my goals would put their time as dashed blocks in free gaps (never in the past, never over anything). Click one to add just that sitting; "Add all to Plan" (with a preview) or "Dismiss" (for that week); "Show suggestions" turns them off. The keyboard block list reads them out ("Suggested: Study 16:00–18:00").
- Timetable: a "Plan this week" panel beside the grid (under it on narrow screens): free hours per day, each hours goal's week as a bar with "Fit N h", Plan all goals, Share hours and I'm away for each day. It replaces the goal chips above the grid.
- Goals page: a pace chart on each goal's card (Actual so far, even pace, "at this rate", today; it reads its numbers out to screen readers), with the state badge and short detail lines including the goal's own week ("This week 7.5 / 12 h done or planned · 4.5 h short"). A side panel shows "Where this week's N h free go" (one bar split by goal, plus Unclaimed, with Plan my goals and Share hours) and the "can't be finished in time" cards. The "This week's time" bars panel is gone (the same numbers were shown twice).
- Home: today's timetable is always one timeline (what happened before now, the Plan after), whatever the Timetable view setting. A "Needs you this week" card lists only goals that are behind or short, each with its pill and "N h to plan", and Plan my goals. The Goals card gives each goal one status line under its bar ("⚠ Behind: 4.5 h under today's pace"); to-dos sit in a matching card.
- Assistant: `confirm_day` and `skip_block` tools; adding or changing an Actual block corrects the day in the same way.
- Stats: time planned vs done per category.

### Changed
- Anything built on the Actual (weekly review, Stats, goal values, pace, follow-through, the recent rate, suggested goals) counts confirmed days only and says how many ("from 5 of 7 days confirmed"). Days already holding Actual blocks are marked confirmed when you update; nothing is deleted or rewritten.
- Goals: a third way to track progress, "Count timetable hours": the Actual hours of a category, or of one activity in it. Deleting the category turns the goal back into one you update yourself.
- Goals meet the timetable: a week's free time is its timetable hours minus calendar events and Plan blocks that serve no goal (nothing fixed is ever moved). Calendar events in a goal's category count towards that goal. All-day events don't block time unless you mark "I'm away" (Timetable → Away days; kept across syncs). Weeks beyond the 8 weeks calendar sync reaches are estimated from the average load.
- Pace for every goal (hours, habit and hand-kept, in their own unit): on track / behind / slipping / can't be reached, this week's need with hours carried from earlier weeks ("9 h this week (6 h + 3 h carried)"), and a projected finish from the last 4 weeks ("11 days late at this rate").
- Honest forecasts: follow-through (Actual ÷ Plan over the last 6 weeks) inflates what to plan ("plan 16 h to land 10 h"); Settings → Region → "Plan extra for time that usually slips" turns it off.
- Timetable: a chip per hours goal above the week, amber when short; clicking opens Fit time pre-filled with the shortfall. "Plan my goals" fills every goal's shortfall into free time, top goal first, with a preview.
- Competing goals: list order is priority (Move up / Move down in a goal's ⋯ menu). When goals want more than the week's free time, "Share hours" shows which are short and lets you split the week your way.
- Goals page: this week's time budget, cards for goals that can't be finished (lower the target, carry the rest into next month or year, or take hours from a lower goal; all undoable, "Not now" hides them), and suggested goals ("3 h/week of Guitar. Make it a goal?").
- Home: a "should be here by today" tick on each goal bar.
- Away days: tick any day of the week as "I'm away" (Timetable → Away days), with or without a calendar event. Sleep is never suggested as a goal.
- Weekly review: a goal pace section. One mid-week notification per goal when what's planned can't cover it.
- Assistant: `goal_pace`, `week_budget` and `plan_goals` tools, goals can count timetable hours (`category`, `label`), and a goals line in its snapshot of today.

## [1.3.0] - 2026-11-07

### Added
- Daily log: a self-rated productivity score for each day, out of 10, in the log, the calendar, Stats, the weekly review, the assistant ("productivity 8") and CSV export / import.
- Blocks: pick the parts of Venato you want in the setup wizard or Settings → Blocks. Each has its own page, Home widget, assistant tools and quick commands; Home shows the widgets in the order you set. Existing installs keep their current pages.
- New blocks: Focus (Pomodoro / stopwatch that fills the Actual timetable), Workouts, Food (diary and meal planner), Recipes (with a shopping list), Cut down (caffeine, alcohol, smoking, screen time, or your own), Grades (weighted marks, classification or GPA), Money (spending, budgets, savings goals, subscriptions, bank CSV import), Involvement (organisations, roles, goals, volunteering, practice, donations, events and tickets) and Health data (Apple Health, Google Fit, Strava and Whoop imports).
- Calendars: add Google, Apple (iCloud) or any other published .ics calendar next to Outlook in Settings → Calendar.
- Assistant is much quicker: it runs on Claude Haiku 5.5 at low effort, keeps one session open between messages instead of starting Claude Code every time, gets a snapshot of today with each message (so it rarely needs to look things up), and streams its reply as it's written, showing what it's doing ("Updating your timetable").
- Quick commands: "drank 500ml", "2 glasses of water", "tick gym", "did gym yesterday", "mood 4", "slept 7.5h", "done finish essay" are done straight away without asking Claude (replies start with ⚡). Settings → Assistant → Quick commands switches them off.
- A local log of how long each assistant message took (`logs/assistant.jsonl` in the data folder; no message text).
- Applications page: a table to track applications (industry, company, route, description, contact / lead, deadline with countdown, status, notes), between Daily Log and Network. Search finds them. Compact rows: text too long for its column ends in "…", which opens the full text in a bubble; status is a colour-coded pill.
- Timetable: click a category again, or press Esc, to deselect it.
- Timetable: with no category picked, dragging over empty time draws a selection box; ⌘/Ctrl-click (as well as Shift-click) adds a block to the selection.
- Assistant: can now list, add, edit and delete applications; rename and delete habits; edit and move to-dos; remove a logged meeting; and save weekly-review answers.
- `CHANGELOG.md`, issue and pull request templates, and `.env.example` listing the environment variables Venato reads.

### Changed
- Timetable: pointing at a block selects it (moving off deselects it), so Delete, ⌘C, dragging and a click for details work straight away; a thinner selection outline.
- Timetable: no more messages under the grid (copied, didn't fit, pick a category...), which also stops the grid shrinking when you copy or paste; deleting or moving blocks no longer shows the Undo bar (⌘Z still undoes).
- Mood and energy are now out of 10 (was 5). Days already logged are doubled once so they match; older CSV exports (without a productivity column) are doubled on import; "mood 4/5" still works.
- Daily log: much bigger mood, sleep, energy and water numbers (and icons) in the month calendar, in a 2 × 2 grid.
- Timetable: the resize bars sit right on a block's top and bottom edges and show whenever you hover a block; drag an edge to resize it without selecting it first.
- Switching pages fades through the page colour and fades the new page in once it has drawn, instead of the old page changing bit by bit.
- Home is built from the switched-on blocks' widgets; Stats moved to its own module.
- Timetable: bigger gaps between blocks and tiles; the whole day fits the window on the Timetable page (rows shrink to fit, like Home); less empty space at the top of every page.
- Timetable: day headers are rounded bubbles with a small gap above the grid; solid, slightly darker time lines; no outline round the table; the help text under it moved into a "?" panel at the top right; "Categories" is now "Adjust categories"; Home's timetable has no colour key.
- Timetable: bigger day names, dates and Plan / Actual labels; the label box at the top right is gone (new blocks take their category's name; rename one in its details).
- Timetable: a click selects a block and a second click opens its details; drag a selected block to move or resize it; dragging from an unselected block draws a box that selects every block it touches. Empty half hours are now soft rounded tiles instead of grid lines.
- Sidebar order: Network now comes before Stats.
- Timetable: the Select, Eraser and Add block buttons are gone; click a block and press Delete or Backspace to remove it, Shift-drag to select several.
- README rewritten: shorter, with badges, a quick start, tech stack and roadmap.
- `CONTRIBUTING.md` now covers setting up, running and opening a pull request.

### Fixed
- Windows: the new blocks' pages (Workouts, Food, Money, Grades, Recipes, Involvement) no longer crash on dates (Windows can't format a day without its leading zero the way Mac and Linux can).
- No grey focus ring after clicking and pressing a key (e.g. Backspace on empty time): focus rings now only show when you use Tab.
- Timetable blocks now sit exactly over their tiles with all four corners rounded (the first column of each day had a square corner, and blocks were slightly out of line).
- The grey focus ring round the page after Backspace or Delete on the timetable in the Mac app (focus is now taken off the page after a timetable shortcut).
- A grey focus ring round the whole page after pressing a key (e.g. Backspace on a timetable block) in the Mac app.
- Backspace on a timetable block edited the label box instead when it still had the cursor.
- README pointed at a "Settings → Claude" tab that doesn't exist; it's Settings → Assistant.

## [1.2.0] - 2026-11-02

### Added
- Smart scheduling: fit N hours of an activity into the Plan's free gaps around your blocks and Outlook events, previewed before adding.
- Network: log times you met or spoke to someone.
- Journal: one free-writing entry per day, with daily prompts and search (lives in the Daily Log).
- Water: litres per day in the Daily Log and Stats.
- Desktop reminders a few minutes before planned blocks and Outlook events start.
- Habits with weekly targets (e.g. Gym 3 times a week), with week-based streaks.
- Deadlines with countdowns, reminders and "Make time".
- Appearance: light, dark or follow the system.
- Text size setting: Small, Normal, Large, Extra large.
- Automatic daily backups to a folder you choose.
- Time zone setting (the computer's, or one you pick).
- Regional settings: week start, 12/24-hour clock, date format, litres or US fl oz.
- Timetable hours: choose when your day starts and ends.
- Undo for deletes and overwrites, from a bar or ⌘Z / Ctrl+Z.
- Update check with a download link when a new release is out.
- Weekly review after 7pm on Sunday, with past reviews on Stats.
- Search everything from Home.
- Timetable: drag blocks to move them and drag their edges to resize; select several blocks to move, copy, paste or delete together; keyboard copy, paste and undo.
- Home: a To-dos heading above the to-do cards.

### Changed
- The Claude assistant is now optional and off by default; everything works by hand.
- Renamed from Arete to Venato, with links and the update check pointing at `venato-app`.
- Every page passes WCAG AA contrast in light and dark; visible keyboard focus everywhere.

### Fixed
- Confirming a change made by Claude crashed (missing import in `chat.py`).
- Backups now close the database files after copying.
- Assorted fixes from the pre-release test pass.

## [1.1.1] - 2026-10-30

### Fixed
- The packaged app was missing its UI modules and failed on launch; `--check` now opens every page inside the bundle.

### Changed
- The sidebar takes no room when closed.
- Quieter installer build logs.

## [1.1.0] - 2026-10-30

Tagged as `v1.1`.

### Added
- Windows support: per-OS data folder, `setup.ps1`, Windows icon and tests on Windows, macOS and Linux in CI.
- Windows installer (`Setup.exe`, PyInstaller + Inno Setup) and Mac `.dmg`, both built and smoke-tested on GitHub Actions.
- Claude via an Anthropic API key, pasted in setup or Settings and kept in the system's secret store.
- Keyboard and screen-reader support across the custom components.

### Changed
- Code moved into a package (`ui/`, `ui/components/`), images into `assets/`, scripts into `scripts/`.
- Workflows run on the public repo only.

### Fixed
- Windows: a date format crashed Home; Claude status and PATH tests made portable.

## [1.0.0] - 2026-10-30

First public version.

### Added
- Home with today's agenda, to-dos, habits to tick (last 7 days and streak) and goal progress.
- Weekly Plan vs Actual timetable with categories.
- To-dos (day, week, month) and measurable monthly and yearly goals.
- Daily log of mood, sleep and energy, with habits.
- Stats charts.
- Network map of groups, sub-groups, people and connections.
- Read-only Outlook calendar via a published ICS link.
- Claude chat box with on-device voice input.

[Unreleased]: https://github.com/spencertomj1-hue/venato-app/compare/v1.3.0...HEAD
[1.3.0]: https://github.com/spencertomj1-hue/venato-app/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/spencertomj1-hue/venato-app/compare/v1.1.1...v1.2.0
[1.1.1]: https://github.com/spencertomj1-hue/venato-app/compare/v1.1...v1.1.1
[1.1.0]: https://github.com/spencertomj1-hue/venato-app/compare/v1.0.0...v1.1
[1.0.0]: https://github.com/spencertomj1-hue/venato-app/releases/tag/v1.0.0
