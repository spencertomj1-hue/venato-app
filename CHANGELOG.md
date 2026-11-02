# Changelog

All notable changes to Venato are listed here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Versions match the git tags and [GitHub Releases](https://github.com/spencertomj1-hue/venato-app/releases).
Venato was called **Arete** up to 1.1.1.

## [Unreleased]

### Added
- `CHANGELOG.md`, issue and pull request templates, and `.env.example` listing the environment variables Venato reads.

### Changed
- README rewritten: shorter, with badges, a quick start, tech stack and roadmap.
- `CONTRIBUTING.md` now covers setting up, running and opening a pull request.

### Fixed
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
