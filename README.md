<!-- TODO: demo.gif -->

<p align="center">
  <img src="assets/Logo.jpg" alt="Venato logo" width="140">
</p>

<h1 align="center">Venato</h1>

<p align="center">
  <strong>A private, offline life tracker for your Mac or PC: plan your week, log what actually happened, and see the gap.</strong><br>
  For students and anyone who wants their timetable, habits, journal, goals and people in one app, on their own computer.
</p>

<p align="center">
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/github/license/spencertomj1-hue/venato-app"></a>
  <a href="https://github.com/spencertomj1-hue/venato-app/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/spencertomj1-hue/venato-app"></a>
  <a href="https://github.com/spencertomj1-hue/venato-app/actions/workflows/tests.yml"><img alt="Tests" src="https://img.shields.io/github/actions/workflow/status/spencertomj1-hue/venato-app/tests.yml?branch=main&label=tests"></a>
  <a href="https://github.com/spencertomj1-hue/venato-app/commits/main"><img alt="Last commit" src="https://img.shields.io/github/last-commit/spencertomj1-hue/venato-app"></a>
  <a href="https://github.com/spencertomj1-hue/venato-app/stargazers"><img alt="GitHub stars" src="https://img.shields.io/github/stars/spencertomj1-hue/venato-app?style=social"></a>
  <img alt="Python 3.13" src="https://img.shields.io/badge/python-3.13-blue">
  <img alt="macOS | Windows" src="https://img.shields.io/badge/platform-macOS%20%7C%20Windows-lightgrey">
</p>

<p align="center">
  <img src="assets/home.png" alt="Venato's Home page" width="800">
</p>

<p align="center">⭐ <strong>Star the repo if you find it useful.</strong> It helps other people find it.</p>

*Venato* comes from the Latin *venari*, to hunt or track down. No summit, just the climb.

## Why this?

- **Plan vs Actual, side by side.** Every day on the timetable has two columns: what you meant to do and what you really did. The weekly review then tells you how much of your plan you followed, per category. Notion and Daylio don't do that out of the box.
- **Your data never leaves your computer.** No account, no server, no cloud sync. Everything is one SQLite file in your data folder, the app only listens on `127.0.0.1`, and voice is transcribed locally.
- **Everything in one place.** Timetable, daily log (mood, sleep, energy, water), journal, habits with streaks, to-dos, goals, deadlines and a map of the people you know, all linked: tick a habit and the goal it counts towards moves; a deadline shows on the timetable and gets a reminder.
- **Optional Claude assistant.** Type or say "Fit 6 hours of revision into next week around my lectures" or "Mood 4, slept 7.5 hours, tick reading". It works through a fixed set of Venato actions, previews anything destructive for you to confirm, and is off unless you switch it on. Everything also works by hand.

## Features

**Pick your blocks.** Venato is built from blocks you switch on in the setup wizard (or Settings → Blocks). Each brings its own page, Home widget and assistant skills, and Home orders the widgets by the priorities you set. The original pages are on by default; the rest are off until you want them:

| Block | What it does |
|---|---|
| **Focus** | Pomodoro or stopwatch with auto breaks; sessions of 15+ minutes go into the Actual timetable. "focus 50 on essay". |
| **Workouts** | Sets, reps, weight, distance; 1RM, personal bests, progress charts, weekly volume, saved plans; kg/lb, km/mi. "bench 3x8 at 60". |
| **Food** | Food diary with calorie and macro targets, and a weekly meal planner. "ate a banana". |
| **Recipes** | Recipes with ingredients and nutrition, and a shopping list grouped by aisle, filled from recipes or the meal plan. "add milk to the shopping list". |
| **Cut down** | Caffeine, alcohol, smoking, screen time or anything else: daily and weekly limits, one-tap presets, streaks, days free, money saved. "had a coffee". |
| **Grades** | Modules and weighted assessments, mark needed for your target, UK classification or US GPA, year weightings. "got 68 in acp coursework". |
| **Money** | Spending and income by category, monthly budgets, savings goals, subscriptions (logged when they renew) and bank CSV import. "spent £12 on lunch". |
| **Involvement** | Societies, clubs, faith, charities, volunteering, work: your role and duties, goals per organisation, hours, practice, donations, events and tickets. "volunteered 3h at oxfam". |
| **Health data** | Import Apple Health, Google Fit, Strava and Whoop exports: steps, sleep, heart rate, HRV, recovery, strain, weight, and workouts. |

**Planning**
- **Weekly timetable** with Plan and Actual columns in 30-minute slots. Drag to add blocks; click a block to select it (click again for details), then drag it to move it or drag its edges to resize; Backspace deletes it; with no category picked, drag a box (or Shift-drag) to select several, Shift- or ⌘/Ctrl-click to add one, then move, copy, paste or delete them together; ⌘Z / Ctrl+Z to undo.
- **Colour-coded categories** in groups ("Life", "Work"), with activities that pick their category automatically ("Lunch" goes to Meals).
- **Fit time:** say what, how many hours and which days; Venato finds free gaps around your blocks and calendar events and previews the sittings before adding them.
- **To-dos** for today, this week and this month, in the style of Apple Reminders: drag to reorder, notes, repeating to-dos.
- **Goals** for the month or year with progress bars, updated by hand or linked to a habit.
- **Deadlines** with countdowns, reminders the day before and on the day, and "Make time" to plan hours for them.

**Tracking**
- **Daily log:** a month calendar of mood, sleep, energy and water. Click a day to tick habits and write notes.
- **Habits:** daily or with a weekly target ("Gym 3 times a week"), with current and best streaks.
- **Journal:** each day's notes, with a daily prompt and a searchable list of past entries.
- **Stats:** charts of mood, energy, sleep and water, plus habit completion rates.
- **Weekly review:** pops up after 7pm on Sunday with plan followed, time per category, mood/sleep/energy/water vs last week, habits, to-dos, deadlines, people you saw and two questions to reflect on.

**Applications**
- **Application tracker:** a table of industry, company, route, description, contact / lead, deadline (with a countdown), status and notes. Compact rows: long text ends in "…" (click it to read it all); click a cell to edit; colour-coded status; filter by status.

**People**
- **Network:** an interactive map of the people you know, grouped into groups and sub-groups, with who-knows-who links.
- **Times you met:** log coffees and calls; each person's card shows when you last spoke.

**Everything else**
- **Search** across to-dos, goals, deadlines, applications, habits, journal, timetable, calendar events, people and past reviews.
- **Calendars (optional, read only):** Outlook, Google, Apple (iCloud) or any .ics calendar shows in the Plan column, synced every 15 minutes.
- **Reminders:** desktop notifications a few minutes before each planned block or event.
- **Undo** for deletes and overwrites, for two minutes.
- **Backups:** automatic daily backups (keeps 30) to any folder, e.g. iCloud Drive or OneDrive, plus CSV export/import and journal download.
- **Settings:** time zone, week start, 12/24-hour clock, date format, litres or US fl oz, timetable hours, light/dark/system theme and four text sizes.
- **Accessible:** keyboard and screen-reader support, and every page passes WCAG AA contrast in light and dark.
- **Update check:** once a day, a banner if a new release is out (can be turned off).

## Screenshots

*All screenshots use made-up demo data.*

| Weekly timetable | Asking Claude |
|---|---|
| ![Weekly timetable](assets/timetable.png) | ![Chat](assets/chat.png) |
| **Daily log** | **Settings** |
| ![Daily log](assets/daily-log.png) | ![Settings](assets/settings.png) |

## Quick start

**Just want the app?** Download it from [Releases](https://github.com/spencertomj1-hue/venato-app/releases/latest): `Venato-Setup.exe` (Windows) or `Venato.dmg` (Apple silicon Mac). They aren't code-signed, so the first launch needs **More info → Run anyway** on Windows, or **System Settings → Privacy & Security → Open Anyway** on a Mac.

**From source (Mac).** Needs [Python 3.13](https://www.python.org/downloads/) (`brew install python@3.13`) and Git.

```bash
git clone https://github.com/spencertomj1-hue/venato-app.git
cd venato-app
./setup.sh
```

`setup.sh` makes a `.venv`, installs the pinned packages and builds **Venato.app** in Applications. Run it again after `git pull`.

**From source (Windows).** Same, but in PowerShell the last step is:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

It adds a Venato shortcut to the Start menu and desktop.

**Run it in a browser (any OS, incl. Linux).** Handy for development:

```bash
git clone https://github.com/spencertomj1-hue/venato-app.git && cd venato-app
python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

The first install downloads about 1 GB of packages; the speech model (about 470 MB) only downloads the first time you use the mic.

## Setting up the optional bits

**Claude assistant.** Off until you switch it on (first-run setup or Settings → Assistant). It uses your own Claude access, one of:
- an **Anthropic API key**, pasted into Settings → Assistant (kept in your system's secret store), or set as `ANTHROPIC_API_KEY`; or
- **[Claude Code](https://docs.claude.com/en/docs/claude-code)** signed in with your Claude account (`claude auth login`). Venato finds it automatically.

Claude can only use Venato's own actions. It has no access to your files, terminal or the web.

It runs on **Claude Haiku 5.5** at low effort, kept open between messages, and replies appear as they're written. Short everyday messages ("drank 500ml", "tick gym", "mood 4", "slept 7h", "done finish essay") are handled straight away without asking Claude; their replies start with ⚡ (switch off in Settings → Assistant → Quick commands). To use a different model, set `"model"` (and optionally `"effort"`) in `venato_config.json`.

**Outlook calendar.** In Outlook on the web: Settings → Calendar → Shared calendars → Publish a calendar, pick **Can view all details**, copy the **ICS** link and paste it into Settings → Calendar. The link is stored in the macOS Keychain / Windows Credential Manager. Anyone with that link can see your calendar, so unpublish it in Outlook to revoke it. Some universities and workplaces block publishing.

**Google and Apple calendars.** Settings → Calendar → Other calendars. Google: calendar.google.com → Settings → your calendar → Integrate calendar → **Secret address in iCal format**. Apple: Calendar on a Mac or iCloud.com → Share Calendar → **Public Calendar** → copy the link. Links are kept in the secret store like Outlook's.

**Health data.** Nothing connects live (Google Fit's APIs close in 2026 and Apple Health has no web API), so you import the files the apps export: Apple Health (Health app → your picture → Export All Health Data; the export.zip, or its path for big ones), Google Fit (Google Takeout → Fit → "Daily activity metrics.csv"), Strava (Settings → My Account → Download your data → activities.csv) and Whoop (Settings → Data export). Venato guesses the columns and shows a preview first; importing the same file again never doubles up.

## Privacy

- **Stays on your computer:** all your data (in `~/Library/Application Support/Venato/` on a Mac, `%APPDATA%\Venato` on Windows, `~/.local/share/Venato` on Linux, never inside the repo), voice recordings and their transcripts, and chat history (memory only, never saved).
- **Leaves your computer only if you turn it on:** chat messages go to Anthropic, each with a short snapshot of today (your timetable for today and tomorrow, today's log, habits, current to-dos, open deadlines and applications in progress, plus a line from each block you've switched on, such as this month's spending or your 7-day health averages) so Claude can answer without looking things up, plus anything else Claude looks up; published calendars you add are downloaded from Microsoft, Google, Apple or wherever they're hosted (imported health and bank files are read on your computer and never sent anywhere); the daily update check asks GitHub for the latest version number.

Nothing else is sent anywhere.

## Troubleshooting

| Problem | Fix |
|---|---|
| "Unidentified developer" on a Mac | Right-click Venato → Open → Open (once). |
| `setup.sh` says Python 3.13 is missing | `brew install python@3.13` (or python.org), then run `./setup.sh` again. |
| Chat says Claude isn't logged in | `claude auth login`, then Settings → Assistant → Check again. |
| Chat can't find Claude Code | Set `claude_path` in `venato_config.json` in your data folder (see `venato_config.example.json`). |
| Mic records silence | Allow Venato in System Settings → Privacy & Security → Microphone. |
| You moved the cloned folder | Run `./setup.sh` again to rebuild Venato.app. |

## Tech stack

- **Python 3.13** with **[Streamlit](https://streamlit.io)** for the UI, plus custom JS/CSS components (timetable, to-dos, network map, chat)
- **SQLite** for storage, **Plotly** and **pandas** for stats
- **[pywebview](https://pywebview.flowrl.com)** for the native desktop window
- **[Claude Agent SDK](https://docs.claude.com/en/docs/claude-code/sdk)** for the optional assistant
- **[faster-whisper](https://github.com/SYSTRAN/faster-whisper)** for on-device speech to text
- **icalendar** / **recurring-ical-events** for calendars, **defusedxml** for Apple Health exports, **keyring** for secrets
- **PyInstaller** and **Inno Setup** for the installers, **GitHub Actions** for tests on Windows, macOS and Linux

## Roadmap

From the "Ideas for later" list in [`HANDOVER.md`](HANDOVER.md):

- [ ] Timetable blocks in CSV export/import (to-dos and goals already have CSVs)
- [ ] "Carry over unfinished" to-dos in the UI (the store function exists)
- [x] Streaming chat replies
- [ ] Signed and notarised Mac app
- [ ] A Linux installer (it runs from source today, in the browser)

Got an idea? [Open an issue](https://github.com/spencertomj1-hue/venato-app/issues/new/choose).

## Contributing

Bug reports, ideas and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) to get set up, and [HANDOVER.md](HANDOVER.md) for how the code fits together. Please never commit real personal data.

## License

[MIT](LICENSE) © Thomas Spencer

⭐ If Venato helps you, a star on GitHub is the easiest way to say thanks.
