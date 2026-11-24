# Changelog

All notable changes to Venato are listed here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Versions match the git tags and [GitHub Releases](https://github.com/spencertomj1-hue/venato-app/releases).
Everything before 1.0.0 was an alpha test. Those releases were first published as 1.0.0 to 1.3.0 and renumbered
0.2.0-alpha to 0.5.0-alpha when 1.0.0 came out. Venato was called **Arete** up to 0.3.1-alpha.

## [Unreleased]

### Added
- **New modules and Canvas courses after setup.** Every sync looks for modules and Canvas courses that aren't in Venato yet. Home's Needs you says how many, and the Modules page has a **New in your calendars** card to Add or Ignore each module and link or Ignore each course. Modules already in Venato (last term's too) are never offered again.
- **Lectures without a code find their module.** A module with no code gets the lectures whose titles have its name, or set your own words under **Lecture titles contain**. A code still wins over title words, and the oldest module wins between two rules. You can also put a whole lecture series on a module, or mark it "Not a module" (Restore it from **Not modules** on the Modules page), and that choice survives every sync. A choice only covers that title under that module's code.
- **Fix links any time.** Each module's page has a **Links** panel: its code, its title words, its Canvas course, and its lecture series, each with **Not this module**. The Modules page has an **Unfiled** card listing lecture series and Canvas deadlines on no module, with a module picker for each. Deleting a module puts its series back in Unfiled.
- **A module's code works as a category.** Typing "CHEM50001" (any case, with or without a space) as a focus or log category, or in a label like "CHEM50001 problem sheet", counts the time for that module. Review has a **Study by module** card: each module's hours that week against its goal.
- **Each module card shows what's linked**: lectures in the next 8 weeks, deadlines and its Canvas course, with a warning when no lectures are found. Assessments and settings now live on the module's own page.

## [1.0.0] - 2026-11-22

Venato now focuses on student life and long-term goals. Home is how you get round the app (the sidebar is gone), goals are plans over months with targets and to-dos under them, setup is a short wizard, and a new install starts blank. Several blocks are gone, but none of their data is deleted (see Removed).

### Added
- **New logo**: a white serif V on a red rounded square, replacing the Greek bust. It's the app icon (Dock, Windows shortcuts, browser tab), and the loading screen shows it with "Venato" and "BETA" underneath (the motto is gone) on the app's paper colour. The loading screen follows dark mode.
- **Long-term goals.** A goal covers 3, 6 or 12 months (or runs to any end date) and has a "why". Under each goal sit its **targets**, which are what goals used to be (measurable, with a deadline, counted by hand, from a habit or from timetable hours), and its **to-dos**. The Goals page shows a card per goal with an overall bar: the average of its targets, or the share of its to-dos done when it has no targets. Targets that aren't under a goal are listed separately. Claude can add, list, change and archive goals. Goals export and import as their own CSV (Settings → Data). Your existing goals become targets under no goal.
- **Each goal has its own colour**, one of eight (never red, which means "behind"), which you can change from the goal's ⋯ menu. The colour shows on the goal's card, its bar, Home's Goals tile and as a small dot beside every to-do under it.
- **Goals that know your week.** A week's free time is its timetable hours minus calendar events and Plan blocks that serve no goal. Pace for every target: on track, behind, slipping or can't be reached, this week's need including hours carried over from earlier weeks, and a projected finish date at your recent rate. Forecasts are honest: plans are padded for time that usually slips (Settings → Region turns this off). The goal list's order sets priority, and **Share hours** splits a crowded week between goals. Targets that can't be finished in time get a card offering to lower the target, carry the rest into the next period or borrow hours from a lower goal. **I'm away** days, suggested goals, and a mid-week nudge when what's planned won't cover a goal.
- **Suggested sittings** on the timetable: when hours targets are short this week, dashed blocks show where Plan my goals would put their time. Click one to add it, or choose **Add all to Plan** or Dismiss.
- **Give it time** beside the timetable: your open to-dos and targets, grouped by goal. Pick one, then drag or click on the week to put it in.
- **To-dos on the timetable.** Unscheduled to-dos show as chips in their day's header. Drag a chip onto the grid to schedule it, and ticking the to-do or its block marks both.
- A **To-dos page** with Today, This week, This month and **By category** tabs, and a category filter that works on every tab. Each goal is also a to-do category, marked with a flag.
- **Setup wizard.** Welcome, then **Your goals** for everyone, then **What would you track?** and **Your first week**. Students also get **Connect your calendars** (Outlook timetable and Canvas) and **Your modules**, and start with a "Do well this term" goal. Everyone else gets a calendar step without Canvas. The last step explains Plan, Actual and Confirm. Every step but Welcome can be skipped, and running setup again only adds things.
- **A blank slate.** A new install has no categories, activities, habits or goals. The old defaults are now examples that setup suggests. Existing installs keep what they have.
- **Modules for students**, each with its own timetable colour, a card on the Modules page and its own page (lectures, deadlines, assessments, study hours, marks). **Canvas and uni timetable feeds** turn into lectures, modules and deadlines. A deadline's **Plan** books hours for it as a target that finishes the day before it's due.
- **Your sleep today** on the Timetable's side panel: enter the times you woke up and went to bed, and Sleep blocks fill the free time before and after them.
- **Send feedback**: a link in the bottom-right corner of every page and in Settings → About opens a short pre-filled form in your browser. Nothing is sent from the app. After 14 days, Needs you asks once how it's going.
- **Needs you** lists the things waiting for you: days to confirm, goals behind or short of time, deadlines this week with no plan, and the odd one-off card.
- Timetable: **Confirm all (N days)** confirms every past day you haven't confirmed yet (after a preview), and a confirmed day can be undone.
- Network has a **Meetings** category. When you mark a meeting Done, it's logged on the Network card of the person it names, or a pop-up asks who it was with.
- Workouts: upload a plan as text or CSV, with a prompt for getting Claude to write one. The plan maker is five steps.
- Assistant: tools for goals, targets, pace (`goal_pace`, `week_budget`, `plan_goals`), `confirm_day`, `confirm_all`, scheduling to-dos, and due times on deadlines.

### Changed
- **Home is how you get round the app; the sidebar is gone.** Every tile opens its page, and each tile's header shows a coloured icon, a name and a short status. Every page has a top bar with "← Home" (Esc does the same) and shortcut tiles. Settings is the gear on Home, and search / Ask is the bar at the top of Home. Pages have addresses (`?page=goals`), so links and the browser's Back button work.
- **Edit Home.** Drag a tile to any cell of a four-column grid, with gaps left where you like. A tile you drop it on swaps places or moves to the nearest free spot. Tiles come in Small, Wide, Large, Tall and **Column** sizes: drag the grip in a tile's corner to resize it, or tap ⤢. − removes a tile (its data stays) and "Add a tile" brings it back. On a laptop (1280×720 and up), Home fits one screen.
- Home's tiles: the **timetable** shows the whole day in a Column tile. **Goals** fits every size, with a bar per goal and a "Next move" in larger sizes. **Review** shows the week's % of plan followed and its verdict. **Focus** is a dial you press to start a stopwatch. **Modules** (was Grades) shows this week's study hours per module. **Journal**, **Daily log** and **Deadlines** show small at-a-glance summaries.
- **Timetable: the Plan is locked when a day starts** and copied into its Actual. After that you change the Actual as the day goes and confirm it at the end. A Plan / Actual switch shows either one. The Plan is drawn as a blueprint, and where a day didn't go to plan, the Plan shows as a faint outline behind what you did. Only confirmed days count in Review and goals, and they say how many. The "Timetable view" setting is gone.
- Timetable: deadlines are small red flags at the time they're due. The "now" line only crosses today. Half-hour blocks show their name on one line. Pointing at a block selects it, and its edges are easier to grab.
- **Review** (was Stats) has a one-screen weekly layout: a ‹ week › stepper, a Week | Trends switch, the week's verdict, last week's promise ("Did you?"), goal pace, a **Next week** card, and planned vs done per category. An **Ask Claude** button gets Claude's take. The Sunday pop-up shows the same layout and only counts as seen once you press Done.
- **The Daily Log is a journal**: it opens on the day's box and prompt, and the calendar marks the days you wrote. Sleep and water are optional (Settings → Daily Log).
- Every block can be switched off in Settings → Blocks. Timetable, Goals, Focus, Review and Daily Log start on, and Modules starts on for students. Workouts and Network are optional blocks.
- Workouts has no preset exercises: type any exercise and it's saved for next time. Only session names go into the timetable.
- New icons for the built-in blocks.
- Faster: Home redraws in about 100 ms instead of 410 ms, Goals in 120 instead of 430, Timetable in 140 instead of 250, and Review in 170 instead of 290. Ticking a to-do takes 9 ms instead of 450 (`docs/perf.md`).
- Charts use Altair (it comes with Streamlit) instead of Plotly, and the installers are smaller.
- Code layout: `venato/store/` and `venato/tools/` are packages with one module per area.

### Removed
- Money, Food, Recipes, Cut down, Health data, Involvement and Applications. Their data stays in your database, untouched: nothing is deleted, it just isn't shown or searched any more.
- Mood, energy and productivity in the Daily Log. The old columns stay in your database.
- The sidebar, the "Timetable view" setting and the Arrange mode (replaced by Edit Home).
- The Plotly and defusedxml dependencies.

### Fixed
- In dark mode, red buttons have dark text.
- No grey focus ring left behind after Esc or Back. Leaving a page fades out cleanly, and Home's tiles no longer glide in from old places.
- Timetable: a block is no longer chopped where time has passed.
- Search no longer lists the closed plan goal of a deadline you've finished.
- Needs you: "N h to plan" no longer overlaps the goal's bar.
- Setup reads your calendars once instead of on every click, and pasting a link you've already connected says "Already connected".
- `scripts/seed_demo.py` runs again.

## [0.5.0-alpha] - 2026-11-07

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
- Timetable: days that haven't happened yet no longer show as Confirmed. Upgrading marked every day with an Actual block confirmed, future ones too; those are cleared on the next start, and a day that hasn't started can't be confirmed (nor by filling in its Actual in the side-by-side view).
- Windows: the new blocks' pages (Workouts, Food, Money, Grades, Recipes, Involvement) no longer crash on dates (Windows can't format a day without its leading zero the way Mac and Linux can).
- No grey focus ring after clicking and pressing a key (e.g. Backspace on empty time): focus rings now only show when you use Tab.
- Timetable blocks now sit exactly over their tiles with all four corners rounded (the first column of each day had a square corner, and blocks were slightly out of line).
- The grey focus ring round the page after Backspace or Delete on the timetable in the Mac app (focus is now taken off the page after a timetable shortcut).
- A grey focus ring round the whole page after pressing a key (e.g. Backspace on a timetable block) in the Mac app.
- Backspace on a timetable block edited the label box instead when it still had the cursor.
- README pointed at a "Settings → Claude" tab that doesn't exist; it's Settings → Assistant.

## [0.4.0-alpha] - 2026-11-02

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

## [0.3.1-alpha] - 2026-10-30

### Fixed
- The packaged app was missing its UI modules and failed on launch; `--check` now opens every page inside the bundle.

### Changed
- The sidebar takes no room when closed.
- Quieter installer build logs.

## [0.3.0-alpha] - 2026-10-30

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

## [0.2.0-alpha] - 2026-10-30

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

[Unreleased]: https://github.com/spencertomj1-hue/venato-app/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/spencertomj1-hue/venato-app/compare/v0.5.0-alpha...v1.0.0
[0.5.0-alpha]: https://github.com/spencertomj1-hue/venato-app/compare/v0.4.0-alpha...v0.5.0-alpha
[0.4.0-alpha]: https://github.com/spencertomj1-hue/venato-app/compare/v0.3.1-alpha...v0.4.0-alpha
[0.3.1-alpha]: https://github.com/spencertomj1-hue/venato-app/compare/v0.3.0-alpha...v0.3.1-alpha
[0.3.0-alpha]: https://github.com/spencertomj1-hue/venato-app/compare/v0.2.0-alpha...v0.3.0-alpha
[0.2.0-alpha]: https://github.com/spencertomj1-hue/venato-app/releases/tag/v0.2.0-alpha
