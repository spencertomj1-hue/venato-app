# Changelog

All notable changes to Venato are listed here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Versions match the git tags and [GitHub Releases](https://github.com/spencertomj1-hue/venato-app/releases).
Venato was called **Arete** up to 1.1.1.

## [Unreleased]

### Added
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
- Daily log: bigger mood, sleep, energy and water numbers (and icons) in the month calendar.
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

[Unreleased]: https://github.com/spencertomj1-hue/venato-app/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/spencertomj1-hue/venato-app/compare/v1.1.1...v1.2.0
[1.1.1]: https://github.com/spencertomj1-hue/venato-app/compare/v1.1...v1.1.1
[1.1.0]: https://github.com/spencertomj1-hue/venato-app/compare/v1.0.0...v1.1
[1.0.0]: https://github.com/spencertomj1-hue/venato-app/releases/tag/v1.0.0
