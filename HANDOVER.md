# Venato — developer guide

How Venato is put together, the decisions behind it, and the pitfalls to know before changing it. For what the app does and how to install it, see the [README](README.md).

## 1. Running and testing

```bash
./setup.sh                                               # Python 3.13 check, .venv, pinned packages, builds Venato.app
.venv/bin/python desktop.py                              # the app in its own window (what Venato.app runs)
.venv/bin/streamlit run app.py                           # the app in a browser (development)
.venv/bin/python -m pytest -q -p no:logging tests        # the test suite
.venv/bin/python scripts/seed_demo.py                    # a demo data folder with fake data
VENATO_DATA_DIR=<folder> .venv/bin/streamlit run app.py   # run against any data folder
```

- **Restart after changes:** Streamlit only hot-reloads `app.py`. Any other module, and the components' JS/CSS (read once at import), need a restart.
- **Never test against real data:** tests and demos must set `VENATO_DATA_DIR` to a temporary folder (the pytest fixtures do).

## 2. Where things live

| What | Where |
|---|---|
| Code | the cloned folder. **Nothing user-specific is ever written here.** |
| User data | `system.default_data_dir()`: `~/Library/Application Support/Venato/` (macOS), `%APPDATA%\Venato` (Windows), `~/.local/share/Venato` (Linux), or `$VENATO_DATA_DIR`: `life.db`, `settings.json`, `backups/`, `.outlook_cache.ics`, optional `venato_config.json`, and `agent/` (the Claude Code working folder) |
| Outlook calendar link | the OS's secret store via `keyring` (macOS Keychain / Windows Credential Manager), service `Venato`, account `outlook-ics-url` |
| Speech model | `~/.cache/huggingface` (downloaded by faster-whisper on first use) |
| Venato.app | `/Applications/Venato.app` or `~/Applications/Venato.app`, built by `setup.sh`. Its launcher script holds the clone's path, written at build time. |
| Windows shortcuts | Start menu and desktop `Venato.lnk`, made by `setup.ps1`: `.venv\Scripts\pythonw.exe desktop.py` (no console window), icon `assets/icon.ico` |

## 3. Files

```
app.py                         Streamlit entry: global CSS, wizard gate, sidebar nav, Home/Stats pages, chat bar, Outlook autosync
desktop.py                     Native window launcher with a splash screen (pywebview); what Venato.app / the Windows shortcut runs
setup.sh                       One-command install on macOS (venv, packages, Venato.app)
setup.ps1                      One-command install on Windows (venv, packages, Start menu + desktop shortcuts)
.github/workflows/tests.yml    Runs the tests on Windows, macOS and Linux for every push

venato/                         The app's code, as a package (imported as `from venato import store`, ...)
  regional.py                Week start, clock, date format, water units (display only; data stays HH:mm / ISO / litres): use its time() / day_month() / long_date() / water_text()
  system.py                    Everything that differs by OS: data folder, opening a folder, words for the UI
  store.py                     ALL SQL; timetable painting rules; settings.json; stats. No Streamlit.
  tools.py                     What Claude can do: plain functions over store.py, previews for destructive changes
  assistant.py                 Claude via claude-agent-sdk: finds the CLI, system prompt, in-process "venato" MCP server
  voice.py                     Microphone recording (sounddevice) and local transcription (faster-whisper)
  outlook.py                   Read-only Outlook import: link checks, Keychain, fetch, recurrence expansion, sync
  notify.py                    Reminders: a background thread that notifies before Plan blocks / Outlook events start
  updates.py                   Daily check of GitHub's latest release vs venato/VERSION (written by packaging/venato.spec; none = "dev", not checked); banner in app.py
  review.py                    Weekly review numbers (summary, due_week: from 7pm Sunday); ui/review.py shows the pop-up and Stats' history; reflections in `weekly_reviews`
  undo.py                      Undo: whole-database snapshot before deletes / overwrites (ui/undo_bar.py offers it)
  setup_checks.py              Logic behind the wizard/Settings: Claude status, mic test, backups, Finder
  training.py                  The 8-week half-marathon plan template and how it's laid on dates (no SQL)
  joint.py                     Joint calendar: partner link (keyring), reading calendars with the "!" privacy rule
  code_mode.py                 "Let Claude edit the app": availability, git snapshot/commit/undo, extra system prompt
  phone.py                     Talk to Venato from the phone: a small PIN-protected web server on the Tailscale address
  autoplan.py                  Puts training sessions on the timetable on every load (to-dos stay off it)
  blocks/personal.py           This copy's own blocks: To-dos, Training, Joint calendar, Start Working's nudge
  ui/                          One module per page or section (imported as `from venato.ui import goals`, ...)
    search.py                  Home's search box: store.search (every word, any case, per kind) and Open (sets page + day / person)
    timetable.py               Timetable page and the week/day grid's Python side
    timetable_tools.py         Buttons above the grid: Add block, Fit time, Categories (dialogs calling the same tools.py functions as Claude)
    training_ui.py             Training page (weeks of sessions to tick, log, move) and Home's "Today's training" and Km run
    joint_ui.py                Joint calendar page: a week as plain HTML, two lanes per day, partner link setup
    daily_log.py               Daily Log page (month calendar, day card, the day's habits, entry form with the journal box, past entries) and Home's habits
    todo_page.py               the To-dos page (due day, the user's own to-do categories, length; the add pop-up)
    todos.py                   Home's to-do cards, with to-do category filters
    work.py                    Start Working: session list, the bars and pot, delegation plan
    goals.py                   Goals page and Home's goal bars (native Streamlit widgets + an HTML bar)
    network.py                 Network page: the web's Python side, plus the add / edit dialogs (incl. the interaction log)
    chat.py                    The chat bar / Home ask box, and its flow (send → transcribe → Claude → rerun)
    settings_ui.py             First-run wizard and the Settings page
    appearance.py              Light / dark / system: syncs settings.json "theme" into Streamlit's own theme choice (localStorage), is_dark()
    sidebar_theme.py           The sidebar's look: marble background, no title, narrow, a box per menu item
    components/                Front ends (Streamlit components v2, shadow root), read once at import:
      timetable_component.*    the week/day grid
      todos_component.*        the Reminders-style to-do lists
      network_component.*      the people web (SVG + a small force layout, no libraries)
      calendar_component.*     the month calendar
      chat_component.*         the chat bar

assets/                        Logo, app icon (icon.png, Venato.icns), splash screen (splash.html/.png),
                               sidebar background (sidebar.webp) and the README screenshots
scripts/
  seed_demo.py                 Demo data folder (never touches real data)
  make_icon.py                 Builds assets/icon.png, Venato.icns and splash.png from assets/Logo.jpg
  install-hooks.sh             gitleaks pre-commit hook
tests/                         pytest + AppTest; tests/fixtures/sample.ics is a fake calendar
```

## 4. Data model (`store.py`)

| Table | Contents |
|---|---|
| `entries` | Daily log: `date` (PK), `mood` 1–5, `sleep` hours, `energy` 1–5, `notes`, `water` litres (added by `_add_column`; `save_entry(water=KEEP)` leaves it alone) |
| `habits`, `habit_log` | Habits (`per_week`: NULL = every day, else a weekly target 1–7), and one row per (habit, date) ticked. Cascade delete. Weekly habits: `week_ticks`, `weekly_streaks` (weeks that hit the target), `habit_progress` gives the one-line summary; Stats counts them as % of the target. |
| `tt_categories` | `id`, `name`, `colour` (#RRGGBB), `text_colour` (NULL = automatic), `grp` (heading in the key), `ord` |
| `tt_label_map` | Activity label → default category (case-insensitive lookups) |
| `tt_entries` | The user's timetable blocks: `id`, `date`, `track` (plan/actual), `start`/`"end"` ("HH:mm", end exclusive, may be "01:00"), `label`, `category_id`, `details` |
| `tt_outlook` | Imported Outlook events, **fully replaced on every sync**: `uid`, `date`, `start`/`"end"` (snapped; NULL if all-day), `title`, `location`, `all_day`, `exact` (real times), `description` |
| `tt_outlook_hidden` | Outlook occurrences the user removed or detached (kept across syncs) |
| `todos` | `id`, `title`, `notes`, `period` (daily/weekly/monthly), `period_start` (the day, its Monday or the 1st), `done`, `done_at`, `"repeat"`, `ord`, `created_at` |
| `todo_rollover` | Per period kind, the last period repeating to-dos were copied into (see §5b) |
| `net_groups` | Network groups: `id`, `name` (unique, any case), `colour`, `ord`, `parent_id` (the group it's inside; NULL = top level; no loops). Seeded from `DEFAULT_NET_GROUPS` |
| `net_people` | `id`, `name` (not unique), `description`, `works_for`, `group_id` (`ON DELETE SET NULL`), `created_at` |
| `deadlines` | `id`, `title`, `due` (date), `notes`, `done`, `done_at`, `created_at`. UI in `ui/deadlines.py` (Goals page section, Home list); chips on the timetable header (`outlookAllDay` with `deadline: true`) and agenda; `notify.due_deadlines` announces today/tomorrow once a day from 9 am |
| `net_interactions` | Times the user met/spoke to someone: `id`, `person_id` (cascade), `date`, `note`, `created_at` |
| `net_links` | Undirected connections: `a`, `b` (always `a < b`, enforced by a CHECK), `reason`. Cascade-deleted with either person |
| `training_plans`, `training_sessions` | One plan (creating one replaces the old): `start_date`, `race_date`. Sessions: `week`, `date`, `kind` (easy/long/tempo/intervals/race_pace/strength/shakeout/race), `title`, `distance_km`, `details`, `done`, `actual_km`, `notes`, `done_at`, `ord`. Cascade delete. Moving the race session moves `race_date` |
| `joint_events` | Joint calendar busy times, fully replaced per person (`who` = me/partner) on refresh: `uid`, `date`, `start_min`/`end_min` (minutes after midnight, split at midnight), `title` (NULL unless the event had "!"), `all_day` |
| `goals` | `id`, `title`, `period` (monthly/yearly), `period_start`, `target`, `unit`, `progress` (kept by hand), `habit_id` (NULL = by hand; `ON DELETE SET NULL`), `ord`, `created_at` |

Notes on the schema:
- **New installs start empty:** no timetable categories, activity defaults or network groups, and the blocks' starter lists (Cut down trackers, Money categories, Workouts exercises) aren't added. The user makes their own: in the new-event form ("+ New category…": the paint op carries `newCategory`, and `store.category_by_name(create=True)` makes it), in Categories, or by asking Claude. `store.use_presets()` (settings `presets: true`, or `$VENATO_PRESETS=1`, which `tests/conftest.py` sets) brings the example lists back: `DEFAULT_CATEGORIES` / `DEFAULT_LABEL_MAP` / `DEFAULT_NET_GROUPS` and each block's `STARTER` / seed. Groups are read from the data (`store.groups()`).
- **`end` is an SQL keyword** and must be quoted.
- **Migrations:** columns added later are added by `_add_column` in `init_db`, so existing databases keep working. `_goals_became_todos` handles databases from before the to-do / goal split: their `goals` table (which held to-dos) is backed up to `backups/life-…-before-todos.db`, renamed to `todos` (with `goal_rollover` → `todo_rollover`), and its yearly to-dos dropped.
- **`settings.json`** holds `ai_enabled` (the optional assistant; `store.ai_enabled()`, missing = on for older installs, the wizard writes it and defaults it off), `wizard_done`, `outlook_category`, `reminders` (default on) and `reminder_minutes` (default 5), `auto_backup` (default on), `backup_keep` (30) and `backup_folder` (default data folder/backups). `setup_checks.auto_backup_if_due()` runs on the reminder thread: one backup a day, pruning only plain `life-YYYY-MM-DD-HHMMSS.db` files. Use `store.load_settings` / `save_settings`.

## 5. Timetable

- **Grid:** 72 quarter-hour slots (`store.SLOT_MIN = 15`; the JS has its own `SLOT_MIN`) from 07:00 to 01:00. The New event and Edit boxes have start/end pickers. Slots after midnight belong to the **previous** day (`slot_of` / `slot_time`).
- **`store.plan_paint` is the single source of truth for editing.** Filling slots s..e-1 trims or splits overlapped blocks, and touching blocks with the same label and category merge. It returns `(ops, affected)`, where `affected` = blocks with a different label/category that get overwritten (used for confirm previews).
  - `store.paint` applies it. In the Plan track it first **detaches** any Outlook event in the way, so those are trimmed like any block.
  - The grid's JS has a display-only copy (`planPaint`) so edits show instantly. If you change the rules, change both; `tests/test_store.py` pins the behaviour.
- **Grid ↔ Python protocol:**
  - The component sends ops with an `opId`: `paint`, `upsert`, `delete`, `hide_outlook` and `detach_outlook`.
  - Python applies them in `timetable.apply_grid_op` and acknowledges them in `data.acked`. The JS replays unacknowledged ops on top of incoming data, so a slow rerun never makes the grid flicker.
  - A paint carries the new block's id (`newId`), so both sides agree on it.
- **Views:** `render_page` is the week (editable). `render_today` is Home's single day: view only, with rows sized to fit the window (`fitToWindow`) and the key wrapped underneath.
- **Clicking a block** grows it and opens a details card (title, time, category, location, description), a chip per category (one click changes it; on an Outlook event that makes it the user's own block, like Edit), and Edit and Delete/Remove buttons except on Home. A red line (`showNow`) marks the current time on today's column, refreshed every 30 seconds. Once an event has finished its card also has Done (green) and Not done (black), saved by `store.mark_event` in `event_status`: a to-do's slot becomes a `tdx:` record and the to-do is ticked or re-placed, and a training session is ticked or shown as missed.
- **Block text** is black unless the fill is dark (`contrastText`, luminance threshold 90).

## 5b. To-dos and goals

Two different things:
- **To-dos** are tick-off lists for a day, a week or a month, shown only on Home.
- **Goals** are measurable targets for a month or a year, with progress bars, on the Goals page and on Home.

**Periods (shared):** all period maths is in `store.py` (`start_of_period`, `shift_period`, `end_of_period`, `period_title`), on dates in the user's time zone (`local_today()`). Weeks run Monday to Sunday, like the timetable.

**To-dos:**
- **Repeats:** `roll_todos()` runs whenever Home or a to-do tool loads. Once per period (remembered in `todo_rollover`), each title whose latest earlier copy has repeat on gets an unticked copy, unless the title is already there. A copy the user deletes therefore stays deleted, and turning repeat off on the latest copy stops it.
- **Carry over:** `carry_over(period, start)` copies unticked to-dos into the next period. It's in the store, but not currently in the UI.
- **To-dos page (`ui/todo_page.py`):** each to-do has `due`, `group_id` (the user's own to-do categories in `todo_groups`, not timetable categories) and `minutes`. To-dos never go on the timetable (the user asked for that). (`place` and `category_id` columns exist but are unused.) "Add new to-do" is an `st.dialog`, also behind Home's +. New ones go in today's list if due today or earlier, else this week's (`store.list_for_due`); a to-do without a due day is due at the end of its list's period (`store.todo_due`). Lists are sorted by that day. On Home, the to-do category pills filter both cards, and a to-do added in a card while filtered gets that category.
- **Component (`todos_component.*`, key `home_todos`):** three compact cards with up to 6 to-dos each, then "N more", which expands in place. A container query stacks the cards when the column is under 480px.
- **Protocol:** the same as the timetable grid. The ops are `add`, `toggle`, `edit`, `repeat`, `move`, `delete` and `reorder`, each with an `opId`. `todos.apply_op` saves them, and they're acknowledged in `data.acked` (`todo_acked` in session state). An `add` carries the new to-do's id, so a resent op adds nothing. The JS calls them "goals" internally (`op.goal`, `section.goals`) from before the split.
- **Tick animation:** a ticked to-do stays in place for 650 ms (circle fills, title fades and strikes through), then folds into "Completed (n)", collapsed by default.
- **Editors:** the new-to-do, title and notes boxes are redrawn with their text, caret and focus after every rerun (`restoreEditor`), so typing is never lost.

**Goals:**
- **Value:** `goals_in` / `get_goal` add `value` (current progress) and `habit` (the linked habit's name). Linked to a habit, `value` is the number of days that habit was ticked within the period; otherwise it's the hand-kept `progress`. Deleting the habit unlinks the goal (back to `progress`).
- **Goals page:** two bordered sections (Monthly, Yearly), each with ‹ › and a "This month / This year" jump (`goals_start_<period>`). Each goal shows `value / target unit`, a percentage and a bar. Hand-kept goals have − / + (via `add_goal_progress`); every goal has a ⋯ popover to edit it (including the "Update it myself" / "Count a habit's ticks" choice) or delete it. "New goal" is a popover with the same form.
- **Bars:** HTML in the theme's primary colour (`st.progress` uses a different one), the same on both pages.
- **Home:** this month's and this year's goals as bars, with "See all" (a button whose callback sets the sidebar radio, `page`).

## 5d. Training, joint calendar, merging categories

- **Categories and rules (`ui/categories_ui.py`, under the week grid):** rename, recolour, add and delete. Deleting is `store.merge_categories`, which also records the swap in settings (`replaced_categories`) so the built-in Teams and To-dos categories don't come back. Rules live in `category_rules`: whole-word, any case, longest word wins (`store.rule_category`; `mapLabel` in the grid mirrors it as you type). They come before label defaults and Teams, and a category asked for explicitly still wins.
- **Editing the plan:** each session's ⋯ changes its name, planned distance, day and time; logging a distance ticks it off. The "Edit the plan" switch shows every session in one table (`training_ui.save_plan_edits`). Changing a session's date updates its `week`.
- **Day trackers:** the user's own numbers for each day (settings `day_trackers`: `[{id, name, unit, step}]`; values in `day_values`), made under the journal ("Manage trackers") or by Claude (`add_tracker`, `log_tracker`, `list_trackers`). They show on the journal's left page (− / + by their step) and as charts at the bottom of Stats (`ui/my_stats.py`). Blank means not logged and 0 means none. Nothing about them is in the code.
- **Training plan (`training.py`):** a fixed template of 8 weeks (Base, Base, Build, Cutback, Build, Peak, Taper, Race week) with sessions on weekdays (long run Sunday). Sessions per week 3,3,4,4,5,5,5,4; running km 18, 20, 22, 18, 25.5, 29, 23, then race week. Rules it follows: about 10–20% more a week (the 10% rule is loose at low mileage), a cutback week every 3–4 weeks, mostly easy running (~80/20), strength from week 3, and a 20–30% taper. `generate(start)` lays it on dates: if the plan starts mid-week, week 1's sessions are spread over the days left (long run still Sunday); too few days left and it starts next Monday. The race is week 8's Sunday.
- **Joint calendar (`joint.py`):** the privacy rule is applied *while reading* (`rows_from` → `shown_title`), so hidden titles, locations and notes never reach the database. "Mine" is re-read from `outlook.CACHE` (kept fresh by the Outlook autosync); the partner's calendar is downloaded when the page opens, at most every 15 minutes (`partner_synced` in settings), or on ↻. Its link is in the keyring (`Venato` / `partner-ics-url`); never log or show it. The page is plain HTML (no component): hours 07–24, widened to fit events.
- **Autoplan (`autoplan.py`, run by `app.py` on every load):** training sessions (not done, not past, not taken off) get a block if they have none. Unticked daily/weekly to-dos from earlier periods move into the current list (`bring_forward_todos`). To-dos are **not** put on the timetable: `run()` deletes any `td:`/`tdx:` blocks (`store.clear_todo_blocks`). `schedule_todos` is kept, unused except by tests, in case that's wanted back; it worked like this: open to-dos (today's daily + this week's weekly, `off_timetable = 0`) get a 30-minute block `td:<id>` in the to-dos category (created on first use): daily in the next free half hour 09:00–22:00 today, weekly on Sunday 10:00–20:00, then Saturday, then any free time in the next week. A block that's still ahead is kept (so moving it by hand sticks); one whose time has passed is re-placed. Unticked daily/weekly to-dos from earlier periods move into the current list (`bring_forward_todos`). Ticking, deleting or moving a to-do removes its block. Deleting an Venato-made block on the timetable (grid or Claude) sets `off_timetable`, so it isn't put back. Only free time is ever used.
- **Monthly to-dos are retired:** Home shows daily and weekly lists (`HOME_TODO_PERIODS`) and Claude can't add monthly ones; the store still supports them so old data and CSVs work.
- **Journal (`journal.py`, `journal_component.*`):** the Daily Log's notes are the journal. The component keeps one `Journal` instance on its element so typing survives reruns; it sends `save` every 800 ms while typing (`final: false`, text only) and `final: true` on blur, page turn or close, when `journal.save` turns "quoted" text into that day's to-dos and ^caret^ text into that week's (one-offs, recorded in `journal_todos` so they're never added twice). `open` / `nav` triggers set `journal_open` / `log_day`.
- **Journal left page:** mood/energy (1–5 buttons), sleep (± 0.5 h), the day's training sessions and habits, all ticked in the book (`log`, `habit`, `session` triggers → `store.set_entry_field`, `set_habit_done`, `update_session`). Home's habit and training checkboxes set their state from the database each run so ticks made in the book show there.
- **Strava (`strava.py`, `strava_ui.py`):** OAuth with a one-off redirect catcher on `127.0.0.1:8766` (`http://localhost:8766/strava/callback`; the Strava app's callback domain must be `localhost`). Tokens (6 h, refreshed; the refresh token can change) and the app's secret are in the keyring (`Venato` / `strava-app`, `strava-tokens`). `sync` runs from an `st.fragment(run_every=30 min)` in `app.py`, pulls activities since the last sync (60 days first), saves them in `strava_activities`, and ticks off that day's training run once per activity (`session_id`).
- **Stats:** `store.runs()` = Strava runs + training runs ticked off without a Strava run (no double counting); the chart has one bar per run. `store.gym_volume()` = kg per exercise per session (weight × sets × reps), shown for one exercise at a time with the change vs the previous session.
- **Gym log:** `gym_sessions` + `gym_exercises` (exercise, sets, reps, weight_kg), `store.save_gym_session` (replaces a session's exercises), shown under the plan on the Training page with `st.data_editor`. Logging one ticks off that day's strength session. Claude: `log_gym_session`, `list_gym_sessions`, `last_lift`.
- **Home's timetable is editable** (`editable: true` with the compact `readonly` look): highlight to add, drag to move, click to edit or delete. The colour key is hidden everywhere (the new-event form picks the category).
- **Training ticks:** checkboxes on Home and the Training page set their state from the database every run, so a tick on one shows on the other; a done session's block gets a "✓ " label.
- **Timetable shows Plan only:** `render_grid` passes `tracks: ["plan"]` and only plan blocks; the JS draws one column per day. The `track` column and Actual data stay in the database (Stats still reads both), so Actual can come back by passing both tracks.
- **Block editor times:** changing a block's start/end sends `delete` + `paint` (with `newId` = the block's id and its details), so the moved block trims what it now covers, like painting.
- **Training on the timetable:** `tools.place_session` → `store.place_session` puts a session as block `tr:<session id>` (`training_sessions.block_id`) at its start time (`training.start_time`: settings `training_times`, weekday 18:00 / weekend and long runs 09:00) or the nearest free time (`_free_start`: never over the user's blocks or Outlook events), length ≈ 6.5 min/km + 15 min. `edit_session` keeps the block in step; `delete_plan` removes the blocks. A block the user deletes from the timetable just leaves the session off it.
- **Goals have a kind** (`goals.kind`): `simple` (default in the UI and for Claude without a target; done / not yet, `done_at`, via `set_goal_done` / `complete_goal`) or `target` (the counting kind).
- **Habits can be renamed** (`store.rename_habit`, Daily Log → Manage habits, Claude's `rename_habit`); history and linked goals stay.
- **Weekly to-dos repeat by default** (`store.REPEAT_BY_DEFAULT`): new weekly to-dos come back unticked every Monday via `roll_todos`. Right-click → Repeat turns it off for one.
- **Merging categories** (`store.merge_categories`, Claude's `merge_categories`, confirm first): blocks and activity defaults move to the target, Outlook's category follows, and the source leaves the key. It's also how a category is removed.
- **Timetable new-event form:** in the week grid, a drag (or click on an empty slot) highlights the range and opens a small form (name, category); Add paints it. The toolbar's label/category only pre-fill the form; the eraser still erases straight away.

## 5f. Start Working (`ui/work.py`, `work_component.*`)

- **Opening it:** a green button at the bottom of the sidebar (`work.sidebar_button`). It isn't in `PAGES`: it sets `st.session_state["page"] = None` and `work_open`, and `app.py` draws `work.render_page` when nothing is selected. No chat bar on it.
- **Session list (first thing on the page):** the user says (Speak: `voice.recorder`, transcribed into the box) or types what needs doing; `store.split_session_text` splits it on sentences, new lines, numbering and words like firstly / then / finally, and drops filler ("okay so I need to"). Each item (`work_session`, per day) is matched to an open to-do (`match_todo`: shared words) and a bar (`match_track`: the words the user gave each bar, longest match wins, and a count only right before one of them, e.g. "send 5 emails"). Ticking an item ticks its to-do and adds to its bar; unticking undoes both. The links can be fixed in each item's ⋯. The bars, targets and plan show once every item is ticked (or "Show the bars anyway" / "Skip").
- **The game: everything is the user's own** (nothing preset; "Set up" on the page, `store.save_work_setup`): areas (`work_areas`: `[{id, name, colour}]`, the page's sections; three areas = the first on the left third, the other two stacked on the right), bars (`work_bars`: `[{key, area, name, verb, weekly, base, step, words}]`), pots (`work_pots`: `[{key, name}]`), the reward per level (`work_reward`, default 5) and the delegation questions (`work_questions`). A bar's key is made from its name once and never changes, so renaming keeps its counts (`work_log.track`). Level bars count towards the current level (`settings.work_level`); `store.work_targets(level)` is `base + step × (level − 1)`. When all of them reach their targets, `work_tap` adds the reward to `work_wallet` and moves to the next level. Weekly bars count this week's taps (from Monday, `store.work_week_start`) against their `base` and never complete a level. `work_spend` takes money out to one of the pots. One plain, static look (Streamlit theme colours); ops follow the to-dos' ack pattern. Claude: `list_work_bars`, `log_work` (by bar name).
- **Plan:** `work_plan` tasks that must each be decided as me / delegate (to whom) / drop. One of the user's delegation questions (`work.delegate_question`, changes hourly; none set = none shown) shows on the plan and at the top of Home's right column. (The repeated workflow was removed; old `work_workflow*` and `work_theme` settings are ignored.)
- **Goal categories:** `goals.category` names one of `settings.goal_categories` ({name: colour}); Home groups goals under each category in its colour.
- **Km run on Home** (`training_ui.km_goals`): km run this week, this month and over the whole plan, against the plan's planned km for each.

## 5e. "Let Claude edit the app" (`code_mode.py`)

- **Off by default.** Settings → Claude has the switch (`claude_edits_code` in settings.json). Only offered when running from a git clone with git installed, not in the packaged builds.
- **When on:** `_ask` adds Claude Code's `Read`, `Edit`, `Write`, `Glob`, `Grep` and `Bash` tools, runs in the app folder, allows 80 turns and a 30-minute timeout, and appends `code_mode.system_prompt()` (read HANDOVER first, run tests, never commit, never touch the real data folder).
- **Safety net:** `run_turn` snapshots `git status` (with content hashes) before the message and commits just the files that changed during it as "Venato chat: <request>". The user's own uncommitted edits stay uncommitted, unless Claude edited the same file. Settings lists these commits with Undo (`git revert`).
- **Seeing changes:** after a code-changing message, `chat.reload_app_code()` drops `venato.*` from `sys.modules` so the rerun imports the new code.

## 5c. Network

- **Tree:** You → a hub circle per group (ids `g:<group id>`) → sub-group hubs → people; ungrouped people hang off You. Only groups with someone in them (or below them) get a hub. Tree lines are solid and tinted with the parent's colour; person-to-person links are dashed.
- **Web (`network_component.*`, key `network`):** SVG drawn once per data change; positions come from a small force simulation (repulsion, with hubs and You pushing harder; springs along tree lines, short for people, longer for groups; weak springs for cross-links; a weak pull to the centre; speeds capped). New data is pre-settled for up to 400 steps, then fitted to the frame the first time. Labels scale up when zoomed out (`--label`). Positions, pan/zoom and hidden top-level groups are kept in sessionStorage. A dragged circle stays where it's dropped.
- **Cards and dialogs:** selection is local to the JS. Card buttons send `edit` `{kind: person|group, id}`, `{kind: new_person, group}` or `{kind: new_group, parent}`; `_on_edit` stores it in `net_edit`, and `render_page` pops it and opens the matching `st.dialog` once (clicks inside a dialog rerun only the dialog). Dialog buttons are never disabled: Streamlit text boxes only commit on Enter/blur, so they validate on click instead.
- **Claude:** `add_person`, `update_person`, `connect_people`, `disconnect_people` (confirm), `delete_person` (confirm), `add_group` (with `inside`), `edit_group` (rename/recolour/move), `delete_group` (confirm; its people and sub-groups move up a level), `find_people` (lists groups as a tree). Names aren't unique: lookups match an exact name first, then part of a name, and several matches is an error that lists them. Everyone is implicitly linked to the user, so there's no "me" person.

- **Interaction log:** `net_interactions`, newest first. The person dialog adds/removes entries; the card shows "Last spoke" and the latest 3 (`recent` in the component data). Claude: `log_interaction`, `person_history`; `find_people` shows the last one.

## 5d. Journal and reminders

- **Journal = the day's notes (`entries.notes`):** `get_journal` / `save_journal` / `append_journal` / `journal_entries` work on that column (`save_journal` leaves the numbers alone and drops a row left empty). Databases from when the journal had its own `journal` table get it folded into notes by `_journal_became_notes` (appended unless already there) and the table dropped. In the Daily Log the form's widget keys include a hash of the saved entry, so if Claude adds to the day the box shows it instead of a stale draft. Search is `LIKE` per word (wildcards escaped). Claude: `write_journal` appends a paragraph (replace=true needs confirmation), `read_journal` by day, range and/or words. Settings → Data downloads it as Markdown.
- **Reminders (`notify.py`):** `notify.start()` in `app.py` starts one daemon thread per process (skipped when `VENATO_NO_REMINDERS` is set, as the tests do). Every 30 s `check()` reads the settings, finds Plan blocks and visible timed Outlook events from yesterday's and today's timetable days (times before 07:00 are the next calendar day) that start within `reminder_minutes` (or started under a minute ago), and announces each once (key: date|start|label). `system.notify` runs `osascript` (macOS; shows as from Script Editor), a PowerShell toast (Windows) or `notify-send` (Linux), passing the text as arguments / environment variables so nothing in it runs as code.
## 5g. Phone (`phone.py`, `ui/components/phone.html`)

- **What:** a one-box phone page. The user dictates with the phone keyboard's mic and taps Send. The text goes to `assistant.run_turn` prefixed "(From my phone)", with the last 12 phone messages as context. Claude's reply, any Confirm / Cancel previews and today's Start Working list come back as JSON.
- **New Claude tools** (also in the chat): `add_to_session`, `list_session`, `tick_session_item`, `log_work`.
- **Server:** a stdlib `ThreadingHTTPServer` on port 8600. `app.py` calls `phone.ensure_running()` on every load, and it runs as a daemon thread in the Streamlit process.
- **Safety:**
  - It's off until the user switches it on in Settings › Phone, and it needs a 4–12 digit PIN (`settings.phone_pin`), checked on every POST in the `X-Venato-Pin` header. After 5 wrong PINs it locks for 5 minutes.
  - It binds **only** to this computer's Tailscale address (100.64.0.0/10, found with `tailscale ip -4`), and requests from any other address are refused. If Tailscale isn't running it doesn't start, and it retries every 20 s.
- **Limits:** plain HTTP inside Tailscale's encrypted network, so the browser's own speech recognition isn't available (it needs HTTPS). The keyboard mic is used instead. The laptop must be on with Venato open.

## 6. Outlook import (`outlook.py`)

- **Read only:** nothing is ever written to Outlook. The link is only in the Keychain. **Never log or display it.** `fetch()` replaces `requests`' exceptions (which contain the URL) with safe messages, and a test checks this.
- **Parsing:** `icalendar` + `recurring_ical_events` expand recurrences and their exceptions over a window from 14 days back to 8 weeks ahead. Times are converted to the user's time zone (`store.tz()`). Windows timezone names are resolved (with a `WINDOWS_TO_OLSON` fallback).
- **Cancelled events are skipped:** `STATUS:CANCELLED`, and also titles starting "Canceled:"/"Cancelled:", because Outlook keeps meetings cancelled by someone else as CONFIRMED with that title.
- **Fitting to the grid:** `to_rows` intersects each event with every timetable day, snapping start down and end up to 15 minutes. All-day events get one row per day.
- **Descriptions:** `short_description` drops Teams/Zoom join boilerplate and cuts to about 300 characters.
- **User adjustments:**
  - **Remove** hides the occurrence (`tt_outlook_hidden`; uids are stable per occurrence, so it stays hidden).
  - **Edit**, or painting over one, **detaches** it into `tt_entries` as id `ol:<uid>`, with location and description in `details`.
  - **Claude** sees these events with ids `outlook:<uid>`.
- **Sync:**
  - **When:** an `st.fragment(run_every=15 min)` at the end of `app.py` runs once on open and then every 15 minutes, plus the ↻ button.
  - **Cache:** the last good `.ics` is cached in the data folder. Offline, the cache is re-parsed and the header says "Offline · events from X ago". With no link connected it says "Outlook not connected".
  - **Reruns:** the app reruns only if `store.outlook_signature()` changed.
- **Category:** set by `store.outlook_category()`, from settings, defaulting to "classes". Claude's `set_outlook_category` tool changes it.

## 7. Claude chat (`assistant.py`, `tools.py`, `chat.py`)

- **Optional:** everything must work by hand. With `ai_enabled` off there's no chat bar, no Home ask box, no Voice tab, and hints don't mention Venato/Claude. Anything Claude can change needs a UI too: when adding a tool, add (or reuse) a button/dialog, ideally calling the same `tools.py` function so rules and Confirm previews match (see `ui/timetable_tools.py`).

- **The agent:** `claude_agent_sdk.query` drives the `claude` CLI: the user's installed Claude Code if `find_claude()` finds one, otherwise the copy bundled inside the SDK (`bundled_claude()`).
- **Signing in:** an Anthropic API key (pasted in the wizard/Settings, checked with Anthropic's free `GET /v1/models`, stored with `keyring` as service `Venato`, account `anthropic-api-key`; or `$ANTHROPIC_API_KEY`) is passed to the CLI as `ANTHROPIC_API_KEY`, which it prefers over a login. Otherwise the user's Claude Code login is used. `setup_checks.claude_status()` reports which.
- **Isolation:**
  - `tools=[]` (no built-in tools) and `allowed_tools` = only `mcp__venato__*`, with `permission_mode="dontAsk"`.
  - `setting_sources=[]`, `strict_mcp_config=True` and `skills=[]`, so the user's own Claude config isn't loaded.
- **No chat on disk:** the CLI runs with `--no-session-persistence`. `chat.py` keeps the conversation in `st.session_state` and sends the last 12 messages as context (`_with_history`).
- **Finding the CLI:** `find_claude()` checks `venato_config.json`, then `$VENATO_CLAUDE_PATH`, `which`, the common install paths and nvm. Finder-launched apps get a bare PATH, so `_env()` adds PATH, USER and HOME; without USER/HOME the CLI can't read its Keychain login.
- **Async:** the SDK runs in a worker thread with its own event loop, so it never clashes with Streamlit's.
- **System prompt:** rebuilt every message, with the current date/time in the user's time zone, the timetable rules, the categories and the confirm rules.
- **Tools:** (plus `merge_categories`; training: `create_training_plan`, `list_training`, `log_session`, `edit_session`, `delete_training_plan`; Start Working: `add_to_session`, `list_session`, `tick_session_item`, `log_work`)
  - `log_day`, `set_habit`, `add_habit`, `list_habits`
  - `add_block`, `update_block`, `delete_block`, `query_blocks`, `query_entries`, `get_stats`
  - `plan_time`: fits N hours of an activity into the Plan's free gaps (`store.free_runs`: around the user's blocks and visible Outlook events) between two dates, within earliest/latest, in sittings of up to `max_block_hours`, spread over evenly spaced days with a 30-minute break between sittings on the same day. Always a preview (Confirm paints them). Never plans in the past (`_first_future_slot`, using `_now()`, which tests pin).
  - `list_categories`, `edit_category`, `set_activity_default`, `set_outlook_category`
  - `log_day` also takes `water` (litres, the day's total; changing it needs no confirmation since it's a running total).
  - Journal: `write_journal`, `read_journal`. Network interactions: `log_interaction`, `person_history`.
  - To-dos: `add_todo`, `complete_todo`, `uncomplete_todo`, `list_todos`, `delete_todo` (confirm first).
  - Goals: `add_goal`, `log_goal_progress`, `set_goal_progress`, `edit_goal`, `list_goals`, `delete_goal` (confirm first). Progress tools refuse habit-linked goals and point Claude at `set_habit`.
  - Both are found by id or title in the current periods: exact title, then part of a title, then the most shared words ("finish problem sheet" → "Problem sheet 4"). Several matches is an error that lists them, so Claude asks.
  - The prompt tells Claude that "today's goals" / "this week's goals" mean to-dos, since goals are only monthly or yearly.
- **Confirm-first:** anything that deletes data or overwrites/trims other data returns `Result(pending=Pending(summary, run))`. The UI shows Confirm/Cancel, and `run()` re-runs the tool with `confirmed=True` against current data.
- **Chat UI:** the bar is fixed to the bottom of the main column on every page except Home, which has no chat (the user asked for it to go; Home's top right is the to-do cards).
- **Flow:** callbacks set `chat_busy`. `chat.render()` draws first, does the slow work (transcribe, then Claude) and then calls `st.rerun()`, so changes show immediately.

## 8. Startup and smoothness

- **Two windows:** `desktop.py` shows the splash at once, then loads the app in a **hidden** window. When the page renders its `#venato-ready` marker (and at least 2 seconds have passed), it shows the app window and closes the splash.
- **Marker placement:** the marker comes before the Outlook autosync, so the network never delays startup.
- **Global CSS first:** `app.py` sends all global CSS as its first element (top padding, sidebar nav, no stale-element dimming, and hiding the marker's gap). Pages must not inject their own top padding.
- **Toolbar:** `.streamlit/config.toml` sets `client.toolbarMode = "minimal"`, along with `server.address = 127.0.0.1`, XSRF protection and no usage statistics.

## 8b. Installers (`packaging/`, `.github/workflows/release.yml`)

- **One PyInstaller recipe** (`packaging/venato.spec`) builds `dist/Venato/Venato.exe` on Windows and `dist/Venato.app` on macOS, with Python and every package inside. `app.py`, `.streamlit/config.toml`, `assets/` and the components are data files; `collect_all` picks up packages with data/plugins (Streamlit, Plotly, keyring, pywebview, the SDK with its bundled CLI, faster-whisper…).
- **The bundle runs itself twice:** the window process starts a copy of itself with `--serve PORT`, which runs Streamlit in-process (`desktop.serve`). `--check` imports every module and sets up a throwaway database. A windowed `.exe` has no console, so output goes to `<data folder>/logs/venato.log`.
- **The workflow** builds both on GitHub's runners, smoke-tests each (`--check`, then `--serve` and `/_stcore/health`), makes `Venato-Setup.exe` (Inno Setup, `packaging/venato.iss`: per-user, no admin, Start menu + optional desktop shortcut) and `Venato.dmg` (`hdiutil`, drag to Applications), and keeps both as downloads on the run. Run it from the Actions tab with a version and "publish" (or push a `v*` tag) to make a GitHub Release with both attached.
- **Not signed:** Windows shows SmartScreen ("More info → Run anyway"); macOS needs "Open Anyway" in Privacy & Security. Signing needs paid certificates (Apple Developer ID, a Windows code-signing certificate). The Mac build is Apple silicon only (`macos-latest`).

## 9. Gotchas

- **Undo:** call `undo.checkpoint("Deleted X")` just before any delete or overwrite (UI or a confirmed Claude change); `ui/undo_bar.py` then offers Undo for 2 minutes. It restores a whole-database snapshot, so it's only offered while SQLite's change counter shows nothing else was saved since.
- **Timetable hours:** `store.SLOTS` / `FIRST_MIN` come from settings.json `day_start` / `day_end` (`_apply_day_hours`, re-run by `save_settings`); never hard-code 36 or 07:00, and don't use them as default arguments (they'd be frozen at import). Blocks outside the hours stay in the database, hidden.
- **Week start:** weekly to-dos are stored under the week's first day, so `store.set_week_start` moves them (±1 day) when it changes. Use `store.week_start_of(day)`, never `day.weekday()`, for week maths.
- **Time zone:** never use `date.today()` / `datetime.now()` for the user's day: use `store.local_today()` / `store.local_now()` / `store.stamp()`. The zone is settings.json "timezone" (Settings → Region) or the computer's (`tzlocal`). The tests pin Europe/London in conftest.
- **Keyboard:** every page is checked by tabbing through it: each stop must show focus (Streamlit's controls draw their own; `appearance.apply_text_colours()` adds rings for the scrollable main area, links and `[tabindex]`; components have their own `:focus-visible`). Streamlit's "Skip to main content" link is the first stop. Headings use `anchor=False` (otherwise each adds an invisible "link to heading" stop). Dialogs close with Esc; the sidebar menu is one radio group (arrow keys).
- **Contrast (WCAG AA):** text must be 4.5:1. Colours for each mode are in `.streamlit/config.toml` (`[theme.light]` / `[theme.dark]`: accent, red/orange/grey text). Components use `--muted` (mixed from the text colour, fine in both modes) rather than fixed greys; captions are overridden in `appearance.apply_text_colours()` (Streamlit fades them to 3.7:1). Don't fade text below `opacity: 0.72`. Check with axe-core's `color-contrast` rule in both modes after UI changes.

- **Always read and write text files as UTF-8** (`read_text(encoding="utf-8")`). Windows defaults to cp1252, which garbles the components' `›`, `…`, `×` etc.
- **No `%-d` (or other `%-x`) in Python date formats:** Windows' `strftime` doesn't support them. Use `x.day` instead. (Plotly's `tickformat` is fine; it runs in the browser.)
- **Accessibility in the components:** the custom parts are keyboard-usable and labelled: to-do titles are focusable (Enter edits, Menu key / Shift+F10 opens the menu, Alt+↑/↓ reorders), the timetable has a hidden-until-focused list of its blocks (`renderBlockList`), network circles are focusable buttons. Keep new interactive bits focusable with an `aria-label`, and keep focus where it was across redraws.
- **OS differences go in `venato/system.py`** (data folder, opening folders, UI words), so the rest of the code stays the same everywhere.

- **The sidebar radio has `key="page"`.** Home's "See all" sets it from a component callback, which runs before the radio is drawn; don't set it anywhere after that.
- **NaN breaks components.** pandas turns SQL NULLs into NaN, which is invalid JSON. `store._read()` converts them to `None`; do the same for anything passed in a component's `data`.
- **`@font-face` doesn't work inside a component's shadow root.** Document-level fonts (like Streamlit's Material Symbols) do apply.
- **Fixed positioning:** the chat bar is `position: fixed` inside a component. That works because Streamlit's containers have no `transform`; a future Streamlit version could break it.
- **Empty element containers still add a 16px gap** in Streamlit layouts. Hide them if you add invisible elements.
- **Tests and the Keychain:** an autouse fixture swaps `outlook.keyring` for an in-memory fake. Modules that tests `importlib.reload` must have it swapped again; see `test_outlook.py` and `test_setup.py`.
- **UI tests:** for the headless browser or pywebview, run the server with `PYTHON_KEYRING_BACKEND=<module>.MemoryKeyring` and an empty `VENATO_DATA_DIR`.
- **The microphone permission prompt** for an unsigned app bundle launched via a shell script can vary by macOS version. A denied permission records silence, which `voice.Recorder` reports as such.

## 10. Ideas for later

- Timetable data in CSV export/import (to-dos and goals have their own CSVs).
- "Carry over unfinished" for to-dos in the UI (the store function exists).
- Streaming chat replies.
- Configurable grid hours (currently fixed at 07:00–01:00).
- Signing and notarising Venato.app.
