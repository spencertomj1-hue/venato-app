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
app.py                         Streamlit entry: global CSS, wizard gate, sidebar nav, Home/Review pages, chat bar, Outlook autosync
desktop.py                     Native window launcher with a splash screen (pywebview); what Venato.app / the Windows shortcut runs
setup.sh                       One-command install on macOS (venv, packages, Venato.app)
setup.ps1                      One-command install on Windows (venv, packages, Start menu + desktop shortcuts)
.github/workflows/tests.yml    Runs the tests on Windows, macOS and Linux for every push

venato/                         The app's code, as a package (imported as `from venato import store`, ...)
  regional.py                Week start, clock, date format, water units (display only; data stays HH:mm / ISO / litres): use its time() / day_month() / long_date() / water_text()
  system.py                    Everything that differs by OS: data folder, opening a folder, words for the UI
  store.py                     ALL SQL; timetable painting rules; settings.json; stats. No Streamlit. `data_version()` goes up on every committed write.
                               Rule: anything that writes the live database outside `store.db()` must call `store.bump_version()` (undo.restore does);
                               writes by another process aren't seen by the cache.
  cache.py                     `cached(fn)`: reads remembered (st.cache_data) until the data changes; key = database, `data_version()`, settings.json mtime, today. No UI; `ui/kit.py` re-exports it
  tools.py                     What Claude can do: plain functions over store.py, previews for destructive changes
  assistant.py                 Claude via claude-agent-sdk: finds the CLI, system prompt, in-process "venato" MCP server
  quick.py                     Quick commands ("drank 500ml", "tick gym"): handled without Claude via the same tools.py actions
  pace.py                      Goals meet the timetable: capacity, budget, pace, debt, follow-through, negotiation, suggestions (§5e). No SQL, no Streamlit UI (it uses `venato.cache` for cached reads)
  blocks/                      Blocks. Core (always on): timetable, goals, focus, grades, stats (shown as "Review"). Optional:
                               log ("Daily Log"), money, workouts. Each has its own tables, migrations, tools, prompt, context,
                               search, weekly-review lines and page (__init__.py: the Block shape; core.py: timetable, goals, log, stats)
  voice.py                     Microphone recording (sounddevice) and local transcription (faster-whisper)
  outlook.py                   Read-only Outlook import: link checks, Keychain, fetch, recurrence expansion, sync
  notify.py                    Reminders: a background thread that notifies before Plan blocks / Outlook events start
  updates.py                   Daily check of GitHub's latest release vs venato/VERSION (written by packaging/venato.spec; none = "dev", not checked); banner in app.py
  review.py                    Weekly review numbers (summary, due_week: from 7pm Sunday); ui/review.py shows the pop-up and Review's history; reflections in `weekly_reviews`
  undo.py                      Undo: whole-database snapshot before deletes / overwrites (ui/undo_bar.py offers it)
  setup_checks.py              Logic behind the wizard/Settings: Claude status, mic test, backups, Finder
  ui/                          One module per page or section (imported as `from venato.ui import goals`, ...)
    search.py                  Home's search box: store.search (every word, any case, per kind) and Open (sets page + day)
    timetable.py               Timetable page and the week/day grid's Python side
    timetable_tools.py         Buttons above the grid: Add block, Fit time, Categories (dialogs calling the same tools.py functions as Claude)
    daily_log.py               Daily Log page (month calendar, day card, the day's habits, entry form with the journal box, past entries) and Home's habits
    todos.py                   Home's to-do cards
    goals.py                   Goals page (cards in two columns per section, side panel) and Home's goal bars (with the "by today" tick)
    goal_chart.py              The Goals page's pace chart: an SVG drawn as an <img> (st.html strips inline SVG), alt text with the numbers; legend() once per page
    goal_time.py               Timetable: the "Plan this week" panel (free hours per day, goal bars with Fit N h, Plan all goals, I'm away) and suggested sittings; Share hours; the Goals page's pace lines, offers and suggestions
    deadlines.py               Deadlines section (Goals page) and Home's list, with "Make time"
    review.py                  Weekly review pop-up and Review's history
    home.py, stats.py          Home (agenda, widgets) and Review (stats.py) pages
    blocks_ui.py               Settings → Blocks; one page module per block (focus.py, money.py, ...)
    undo_bar.py, page_fade.py  The Undo bar; the fade between pages
    chat.py                    The chat bar / Home ask box, and its flow (send → transcribe → Claude → rerun)
    settings_ui.py             First-run wizard and the Settings page
    appearance.py              Light / dark / system: syncs settings.json "theme" into Streamlit's own theme choice (localStorage), is_dark()
    sidebar_theme.py           The sidebar's look: marble background, no title, narrow, a box per menu item
    components/                Front ends (Streamlit components v2, shadow root), read once at import:
      timetable_component.*    the week/day grid
      todos_component.*        the Reminders-style to-do lists
      calendar_component.*     the month calendar
      chat_component.*         the chat bar

assets/                        Logo, app icon (icon.png, Venato.icns), splash screen (splash.html/.png),
                               sidebar background (sidebar.webp) and the README screenshots
scripts/
  seed_demo.py                 Demo data folder (never touches real data)
  make_icon.py                 Builds assets/icon.png, Venato.icns and splash.png from assets/Logo.jpg
  install-hooks.sh             gitleaks pre-commit hook
tests/                         pytest + AppTest; tests/fixtures/sample.ics is a fake calendar; tests/fragment_run.py runs interactions as the browser does (§8)
```

## 3b. Blocks: tiers and hooks (`venato/blocks/`)

- **Two tiers.** `core=True` blocks are always on (`chosen_keys()` adds them even if settings.json lacks them): Timetable, Goals (also to-dos and deadlines), Focus, Grades, Review (key `stats`, in `blocks/core.py`). Optional blocks are switched on only in Settings → Blocks (the setup wizard doesn't ask): Daily Log (key `log`: habits, journal, mood), Money, Workouts. Settings.json `blocks` lists the keys switched on, in the user's priority order, which is also the order of the Home widgets. Removed features (Food, Recipes, Cut down, Health data, Involvement, Applications, Network) have no code; their tables stay in old databases untouched and are never dropped.
- **Hooks on `Block`** (all optional; the shared code asks the switched-on blocks, so a block never needs an `if` somewhere else):
  - `search`: `{kind: (select, haystack[, order])}`, merged by `blocks.search_kinds()` into Home's search; `search_icons`: `{kind: Material icon}` for its results; `search_open(result, session_state)`: routes a click on a result to the block's page (`blocks.search_block(kind)` finds the owner; core kinds have none).
  - `review(first, last)` -> `{"title", "lines"}`: lines for the weekly review (`blocks.review_sections`); no lines = no section.
  - `status`: `{word in a tool's name: text}`: what the chat shows while one of the block's tools runs.
  - Plus the older ones: `page`, `home`, `tools`, `prompt`, `context`, `quick`, `schema`, `migrate`.
- **Adding a block** = adding a file in `venato/blocks/` with a `BLOCK`; set `search*` / `review` / `status` there rather than in `store.py`, `review.py` or `chat.py`.

## 4. Data model (`store.py`)

| Table | Contents |
|---|---|
| `entries` | Daily log: `date` (PK), `mood` 1–5, `sleep` hours, `energy` 1–5, `notes`, `water` litres (added by `_add_column`; `save_entry(water=KEEP)` leaves it alone) |
| `habits`, `habit_log` | Habits (`per_week`: NULL = every day, else a weekly target 1–7), and one row per (habit, date) ticked. Cascade delete. Weekly habits: `week_ticks`, `weekly_streaks` (weeks that hit the target), `habit_progress` gives the one-line summary; Review counts them as % of the target. |
| `tt_categories` | `id`, `name`, `colour` (#RRGGBB), `text_colour` (NULL = automatic), `grp` (heading in the key), `ord` |
| `tt_label_map` | Activity label → default category (case-insensitive lookups) |
| `tt_entries` | The user's timetable blocks: `id`, `date`, `track` (plan/actual), `start`/`"end"` ("HH:mm", end exclusive, may be "01:00"), `label`, `category_id`, `details` |
| `tt_outlook` | Imported Outlook events, **fully replaced on every sync**: `uid`, `date`, `start`/`"end"` (snapped; NULL if all-day), `title`, `location`, `all_day`, `exact` (real times), `description` |
| `tt_outlook_hidden` | Outlook occurrences the user removed or detached (kept across syncs) |
| `todos` | `id`, `title`, `notes`, `period` (daily/weekly/monthly), `period_start` (the day, its Monday or the 1st), `done`, `done_at`, `"repeat"`, `ord`, `created_at` |
| `todo_rollover` | Per period kind, the last period repeating to-dos were copied into (see §5b) |
| `deadlines` | `id`, `title`, `due` (date), `notes`, `done`, `done_at`, `created_at`. UI in `ui/deadlines.py` (Goals page section, Home list); chips on the timetable header (`outlookAllDay` with `deadline: true`) and agenda; `notify.due_deadlines` announces today/tomorrow once a day from 9 am |
| `goals` | `id`, `title`, `period` (legacy tag: monthly if due by the end of its first month, else yearly), `period_start` (the day it was set), `due` (the deadline; older goals got their month's or year's last day), `target`, `unit`, `progress` (kept by hand), `habit_id` (NULL = by hand; `ON DELETE SET NULL`), `ord` (also its priority), `created_at`, `category_id` (counts timetable hours; `ON DELETE SET NULL`; never together with `habit_id`), `label` (optional: only that activity) |
| `goal_week` | The user's split of a week between hours goals: `goal_id` (cascade), `week_start`, `hours`. None = automatic |
| `tt_outlook_away` | All-day calendar events marked "I'm away" (that day has no free time for goals); kept across syncs |
| `away_days` | Days marked "I'm away" by hand (`date`), no calendar event needed |
| `tt_day_status` | Locked / confirmed days (§5f): `date` (PK), `confirmed_at` (NULL = not confirmed: only the user sets it), `upto` ("HH:mm": the day's end once its Plan is locked). Made by `_day_status_table` on first run, marking every day that already had Actual blocks confirmed |

Notes on the schema:
- **New installs** are seeded with generic categories (groups "Life" and "Work") and activity defaults, in `DEFAULT_CATEGORIES` / `DEFAULT_LABEL_MAP`. Groups are read from the data (`store.groups()`), so a user's own groups work too.
- **`end` is an SQL keyword** and must be quoted.
- **Migrations:** columns added later are added by `_add_column` in `init_db`, so existing databases keep working. `_goals_became_todos` handles databases from before the to-do / goal split: their `goals` table (which held to-dos) is backed up to `backups/life-…-before-todos.db`, renamed to `todos` (with `goal_rollover` → `todo_rollover`), and its yearly to-dos dropped.
- **`settings.json`** holds `goal_inflate`, `goal_nudged`, `goal_offers_dismissed`, `goal_suggestions_dismissed` (§5e), `ai_enabled` (the optional assistant; `store.ai_enabled()`, missing = on for older installs, the wizard writes it and defaults it off), `wizard_done`, `outlook_category`, `reminders` (default on) and `reminder_minutes` (default 5), `auto_backup` (default on), `backup_keep` (30) and `backup_folder` (default data folder/backups). `setup_checks.auto_backup_if_due()` runs on the reminder thread: one backup a day, pruning only plain `life-YYYY-MM-DD-HHMMSS.db` files. Use `store.load_settings` / `save_settings`.

## 5. Timetable

- **Grid:** half-hour slots from settings `day_start` to `day_end` (default 07:00 to 01:00, 36 slots; `store.SLOTS` / `FIRST_MIN`, see §9). Slots after midnight belong to the **previous** day (`slot_of` / `slot_time`).
- **`store.plan_paint` is the single source of truth for editing.** Filling slots s..e-1 trims or splits overlapped blocks, and touching blocks with the same label and category merge. It returns `(ops, affected)`, where `affected` = blocks with a different label/category that get overwritten (used for confirm previews).
  - `store.paint` applies it. In the Plan track it first **detaches** any Outlook event in the way, so those are trimmed like any block.
  - The grid's JS has a display-only copy (`planPaint`) so edits show instantly. If you change the rules, change both; `tests/test_store.py` pins the behaviour.
- **Grid ↔ Python protocol:**
  - The component sends ops with an `opId`: `paint`, `upsert`, `delete`, `hide_outlook` and `detach_outlook`.
  - Python applies them in `timetable.apply_grid_op` and acknowledges them in `data.acked`. The JS replays unacknowledged ops on top of incoming data, so a slow rerun never makes the grid flicker.
  - An op Python can't save (a started day's locked Plan, or an error while saving) is acknowledged too, with the reason in `data.rejected` (`{opId: why}`, session state `tt_rejected`). The JS drops it, so the grid shows what was saved (the block goes back), and shows the reason in a note over the grid (`.tt-error`) for a few seconds.
  - A paint carries the new block's id (`newId`), so both sides agree on it.
- **Views:** `render_page` is the week (editable, with the Plan / Actual switch, §5f). `render_today` is Home's single day: view only, its Actual, with rows sized to fit the window (`fitToWindow`) and the key wrapped underneath. (The old `timetable_view` setting is gone; a leftover key in settings.json is ignored.)
- **Clicking a block** grows it and opens a details card (title, time, category, location, description), with Edit and Delete/Remove buttons except on Home. A drag paints, and a click with the eraser erases.
- **Block text** is black or white, whichever has the higher WCAG contrast with the fill (`contrastText`).

## 5b. To-dos and goals

Two different things:
- **To-dos** are tick-off lists for a day, a week or a month, shown only on Home.
- **Goals** are measurable targets with a deadline (`period_start` .. `due`), with progress bars, on the Goals page and on Home.

**Periods (shared):** all period maths is in `store.py` (`start_of_period`, `shift_period`, `end_of_period`, `period_title`), on dates in the user's time zone (`local_today()`). Weeks run Monday to Sunday, like the timetable.

**To-dos:**
- **Repeats:** `roll_todos()` runs whenever Home or a to-do tool loads. Once per period (remembered in `todo_rollover`), each title whose latest earlier copy has repeat on gets an unticked copy, unless the title is already there. A copy the user deletes therefore stays deleted, and turning repeat off on the latest copy stops it.
- **Carry over:** `carry_over(period, start)` copies unticked to-dos into the next period. It's in the store, but not currently in the UI.
- **Component (`todos_component.*`, key `home_todos`):** three compact cards with up to 6 to-dos each, then "N more", which expands in place. A container query stacks the cards when the column is under 480px.
- **Protocol:** the same as the timetable grid. The ops are `add`, `toggle`, `edit`, `repeat`, `move`, `delete` and `reorder`, each with an `opId`. `todos.apply_op` saves them, and they're acknowledged in `data.acked` (`todo_acked` in session state). An `add` carries the new to-do's id, so a resent op adds nothing. The JS calls them "goals" internally (`op.goal`, `section.goals`) from before the split.
- **Tick animation:** a ticked to-do stays in place for 650 ms (circle fills, title fades and strikes through), then folds into "Completed (n)", collapsed by default.
- **Editors:** the new-to-do, title and notes boxes are redrawn with their text, caret and focus after every rerun (`restoreEditor`), so typing is never lost.

**Goals:**
- **Value:** `goals_in` / `get_goal` add `value` (current progress), `kind` (`hours` / `habit` / `count`), `habit` and `category` (names). Linked to a habit, `value` is the number of days that habit was ticked within the period; counting timetable hours, it's the Actual hours of that category (and label) in the period, from `store.goal_hours`; otherwise it's the hand-kept `progress`. Deleting the habit or category unlinks the goal (back to `progress`).
- **Goals page:** one bordered section of the goals not past their deadline (`store.goals_open`), and a "Past goals" expander (`goals_past`). The deadline field is `goals.due_picker` (component `due_picker_component.*`): a scrolling calendar with markers from `handy_deadlines` and "End of the year" / "In a year" shortcuts. Each goal shows `value / target unit`, a percentage and a bar. Hand-kept goals have − / + (via `add_goal_progress`); every goal has a ⋯ popover to edit it (including the "Update it myself" / "Count a habit's ticks" choice) or delete it. "New goal" is a popover with the same form.
- **Bars:** HTML in the theme's primary colour (`st.progress` uses a different one), the same on both pages.
- **Home:** this month's and this year's goals as bars in a card, with "See all" (a button whose callback sets the sidebar radio, `page`), the "by today" tick and one status line each (`goals.status_line`). Above the to-dos, `goal_time.needs_you` lists only goals behind or short this week ("N h to plan") with Plan my goals; both share one `pace.Ctx` (`blocks/core._goals_home`).

## 5d. Journal and reminders

- **Journal = the day's notes (`entries.notes`):** `get_journal` / `save_journal` / `append_journal` / `journal_entries` work on that column (`save_journal` leaves the numbers alone and drops a row left empty). Databases from when the journal had its own `journal` table get it folded into notes by `_journal_became_notes` (appended unless already there) and the table dropped. In the Daily Log the form's widget keys include a hash of the saved entry, so if Claude adds to the day the box shows it instead of a stale draft. Search is `LIKE` per word (wildcards escaped). Claude: `write_journal` appends a paragraph (replace=true needs confirmation), `read_journal` by day, range and/or words. Settings → Data downloads it as Markdown.
- **Reminders (`notify.py`):** `notify.start()` in `app.py` starts one daemon thread per process (skipped when `VENATO_NO_REMINDERS` is set, as the tests do). Every 30 s `check()` reads the settings, finds Plan blocks and visible timed Outlook events from yesterday's and today's timetable days (times before 07:00 are the next calendar day) that start within `reminder_minutes` (or started under a minute ago), and announces each once (key: date|start|label). `system.notify` runs `osascript` (macOS; shows as from Script Editor), a PowerShell toast (Windows) or `notify-send` (Linux), passing the text as arguments / environment variables so nothing in it runs as code.

## 5e. Goals and the timetable (`pace.py`, `ui/goal_time.py`)

- **One helper:** `store.goal_hours(goal, first, last, track, data=None, window=None)` counts an hours goal's category (and label: exact for blocks, contained in the title for calendar events) in a track. The Plan includes visible timed calendar events in that category; detached ones (`ol:` blocks) never count. `pace.Ctx` reads the blocks and events once per page and passes them as `data`; `window(day)` cuts a day to some slots (`ctx.past` / `ctx.future`).
- **Capacity:** per day, the slots from now on that aren't fixed. Fixed = visible timed calendar events + Plan blocks that serve no hours goal active that day (+ every `ol:` block). Time already planned for a goal counts as free for goals. Past days and away days have none; all-day events don't block. Past `calendar_horizon()` (8 weeks, the sync window) a day uses the average fixed load for its weekday and is flagged `estimate`. Sleep isn't subtracted.
- **Need and debt:** `week_need` spreads what was left at the start of the week (now, for later weeks) over the days left, times the week's days in the period (partial weeks work). Baseline = target × days / period days; need − baseline is the carried debt. Computed, never stored.
- **Follow-through:** Actual ÷ Plan for the goal over the last 6 complete weeks with a Plan, needing 3 of them, clamped 30–100%. `want` = done + rest of need ÷ follow-through (or `goal_week`'s hours). Setting `goal_inflate` (default on) switches the inflation off.
- **Budget / competition:** `week_goals` hands the rest of the week's capacity out top-down by priority (`ord`, the sooner deadline on a tie) as `alloc`; `budget_short` is what doesn't fit. Count goals (books, money) get pace and debt but no budget. Yearly goals are budgeted week by week like monthly ones.
- **Pace states:** done; unreachable (hours: remaining > free time left; habit: remaining > days left); behind (covered < want this week; habit/count: below the even-pace line and late at the trailing rate); slipping (planned enough, but Actual trails Plan this week by 1 h+); on track. Projection: the last 28 days' rate (hand-kept: the period so far).
- **Negotiation:** `negotiation(goal)` when remaining > what the goal can get after higher-priority goals (`available_for`), or unreachable: offers lower / carry / take, applied by `tools.resolve_goal` (a Pending; the UI calls `undo.checkpoint`). `goal_offers_dismissed` in settings.json.
- **Suggestions:** categories / activities with 2 h+ of Actual time in 3 of the last 4 weeks and no goal counting them; dismissals in `goal_suggestions_dismissed`. Categories in `pace.NEVER_SUGGEST` (Sleep, by id or name) are never suggested.
- **Nudge:** `notify.goal_nudges` → `pace.nudges`: from midday on the week's third day, once per goal per week (`goal_nudged` in settings.json, so restarts don't repeat it).
- **Claude:** `goal_pace`, `week_budget`, `plan_goals` (shares free gaps between goals via `tools._place`, the same placement `plan_time` uses), and a line in the [Now] snapshot. Buttons: the planner panel / Plan my goals / Share hours / pace lines.
- **Timetable planner (`goal_time.planner`)**: beside the grid (`st.columns`, so it stacks on narrow screens): free hours per day (`week_capacity`), each goal's bar (`_bar`, CSS once from `bar_style()`) with "Fit N h" (`_fit_goal` → `timetable_tools.open_fit`), Plan all goals, Share hours when over budget, I'm away checkboxes. It replaced the chip strip. For a week that's over it's "How the week went": `_score(w, all_confirmed)` per goal (done of that week's need; "missed" only when every day is confirmed, else "short so far") and a count of unconfirmed days.
- **Goals page:** each card: badge (`goal_time.badge`), the value, `goal_chart.chart(p, ctx)` (history from `pace.history`: confirmed-day Actual per day, a point a week for yearly goals; even pace dashed grey; projection dotted from today at `p["rate"]`; a today line), then `goal_chart.week_line` + `p["details"]`. Side panel: `goal_time.free_split` (week_budget allocs per goal + Unclaimed, colours `GOAL_COLOURS` validated light/dark with the dataviz checker), `offers`, `suggestions`.
- **Suggested sittings:** `tools.goal_spots(date)` is the placement `plan_goals` uses (so "Add all to Plan" adds exactly what's drawn). `goal_time.suggestions_for(first)` turns it into grid data (`data.suggestions`, ids `sg:<day>:<HH:mm>`); the JS draws them dashed only where the Plan is still free and the slot hasn't passed (`addGhosts`). A click sends `add_suggestion`; Python paints it only if those slots are still free (`goal_time.add_suggestion`). Settings: `show_suggestions` (default on), `suggestions_dismissed` (week starts).

## 5f. Plan locked at the start of the day, Actual adjusted, then confirmed

- **Data is two tracks.** `tt_entries` keeps `plan` (what you meant to do) and `actual` (what you did). Review, stats, Focus and the assistant read Actual on **confirmed days** only (`store.confirmed_days`); Plan vs Actual compares the two on those days.
- **Lock** (`store.lock_day(day, conn, now, confirm)`): once a day has started (`store.day_started`: `day_start` reached), copies its whole Plan (own blocks + visible timed calendar events, `_plan_items`) into every **empty** Actual slot of the day, never over an Actual block (Focus, hand-entered), and sets `upto` to the day's end. Ids are `m:<day>:<HH:mm>`. Idempotent; a day part-locked by older versions gets the rest. From then on that day's Plan is frozen. It never confirms unless `confirm=True`. `lock_started(first, last, now)` locks every started day in a range: run by `render_grid`, `apply_grid_op` (for the days an op touches), `pace.Ctx.data`, `notify.upcoming` and the timetable tools before they look or change anything, so the Plan can't be edited after its day starts.
- **Where changes go:** `store.live_track(day)` = `"actual"` once the day has started, else `"plan"`. `free_runs`, `plan_time`, `plan_goals` and suggested sittings use it. `pace.Ctx` has a derived track `"live"` (a started day's Actual, else the Plan and its events) for capacity, `planned_future` and `assumed`.
- **Locked Plans are never changed:** `timetable._touches_locked_plan` drops grid ops on a started day's Plan (a grid drawn before the day started); `tools.add_block` / `update_block` move a Plan change on a started day into the Actual, `update_block` / `delete_block` on a locked Plan block raise a ToolError pointing at the Actual.
- **Confirm:** `store.confirm_day` (locks first), `unconfirm_day` (just clears `confirmed_at`; the Actual stays). `mark_confirmed` marks a started day locked and confirmed as it is (tests, hand-filled data). Changes to the Actual (`correct`, `retime`, the grid) never confirm.
- **Grid:** `data.mode` (`"plan"` / `"actual"`, session state `tt_mode`, the Plan / Actual switch sends a `mode` trigger; Home is always Actual), `data.dayState[date] = {gone, locked, confirmed}`. One column a day; `trackFor(di)` is the track it shows (Plan mode: the Plan; Actual mode: the Actual once locked, else the Plan) and is written to each cell's `data-t`, so painting, moving, pasting and deleting act on that track. `frozen(di)` (Home, or a locked Plan) makes a day view only: a click shows the card ("Locked when the day started"), nothing drags, pastes or deletes there. Calendar events are drawn only where the Plan is shown. Header: Confirm / ✓ Confirmed · Undo (Actual), 🔒 Locked (Plan). Ops `confirm_day` / `unconfirm_day`; `skip` / `replace` / `retime` are still accepted (assistant-era corrections).
- **Hover = select:** pointing at a block selects it (a thin red ring, `--sel`); ⌘/Ctrl+C copies, ⌘/Ctrl+V pastes where the pointer is, Backspace/Delete deletes, a click opens the details card, top/bottom edges resize in either direction.
- **Prompts:** Home's `timetable.end_of_day_prompt()`: "Is the timetable right for today?" (Confirm / Review / Not now) once `store.day_ended`, and yesterday if unconfirmed. Review opens the Timetable in Actual mode. Toolbar: "Confirm week (N days)", "Confirm all (N days)".
- **Reminders** (`notify.upcoming`): a started day's Actual (so moving a block today moves its reminder), else the Plan and calendar events.

## 6. Outlook import (`outlook.py`)

- **Read only:** nothing is ever written to Outlook. The link is only in the Keychain. **Never log or display it.** `fetch()` replaces `requests`' exceptions (which contain the URL) with safe messages, and a test checks this.
- **Parsing:** `icalendar` + `recurring_ical_events` expand recurrences and their exceptions over a window from 14 days back to 8 weeks ahead. Times are converted to the user's time zone (`store.tz()`). Windows timezone names are resolved (with a `WINDOWS_TO_OLSON` fallback).
- **Cancelled events are skipped:** `STATUS:CANCELLED`, and also titles starting "Canceled:"/"Cancelled:", because Outlook keeps meetings cancelled by someone else as CONFIRMED with that title.
- **Fitting to the grid:** `to_rows` intersects each event with every timetable day, snapping start down and end up to 30 minutes. All-day events get one row per day.
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

- **The agent:** a persistent `claude_agent_sdk.ClaudeSDKClient` per conversation (kept open between messages, replies streamed with `include_partial_messages`) drives the `claude` CLI: the user's installed Claude Code if `find_claude()` finds one, otherwise the copy bundled inside the SDK (`bundled_claude()`).
- **Signing in:** an Anthropic API key (pasted in the wizard/Settings, checked with Anthropic's free `GET /v1/models`, stored with `keyring` as service `Venato`, account `anthropic-api-key`; or `$ANTHROPIC_API_KEY`) is passed to the CLI as `ANTHROPIC_API_KEY`, which it prefers over a login. Otherwise the user's Claude Code login is used. `setup_checks.claude_status()` reports which.
- **Isolation:**
  - `tools=[]` (no built-in tools) and `allowed_tools` = only `mcp__venato__*`, with `permission_mode="dontAsk"`.
  - `setting_sources=[]`, `strict_mcp_config=True` and `skills=[]`, so the user's own Claude config isn't loaded.
- **No chat on disk:** the CLI runs with `--no-session-persistence`. `chat.py` keeps the conversation in `st.session_state` and sends the last 12 messages as context (`_with_history`).
- **Finding the CLI:** `find_claude()` checks `venato_config.json`, then `$VENATO_CLAUDE_PATH`, `which`, the common install paths and nvm. Finder-launched apps get a bare PATH, so `_env()` adds PATH, USER and HOME; without USER/HOME the CLI can't read its Keychain login.
- **Async:** the SDK runs in a worker thread with its own event loop, so it never clashes with Streamlit's.
- **System prompt:** rebuilt every message, with the current date/time in the user's time zone, the timetable rules, the categories and the confirm rules.
- **Tools:**
  - `log_day`, `set_habit`, `add_habit`, `list_habits`
  - `add_block`, `update_block`, `delete_block`, `query_blocks`, `query_entries`, `get_stats`
  - `plan_time`: fits N hours of an activity into the Plan's free gaps (`store.free_runs`: around the user's blocks and visible Outlook events) between two dates, within earliest/latest, in sittings of up to `max_block_hours`, spread over evenly spaced days with a 30-minute break between sittings on the same day. Always a preview (Confirm paints them). Never plans in the past (`_first_future_slot`, using `_now()`, which tests pin).
  - `list_categories`, `edit_category`, `set_activity_default`, `set_outlook_category`
  - `log_day` also takes `water` (litres, the day's total; changing it needs no confirmation since it's a running total).
  - Journal: `write_journal`, `read_journal`.
  - To-dos: `add_todo`, `complete_todo`, `uncomplete_todo`, `list_todos`, `delete_todo` (confirm first).
  - Goals: `goal_pace`, `week_budget`, `plan_goals` (§5e), `add_goal` (habit or category/label), `log_goal_progress`, `set_goal_progress`, `edit_goal`, `list_goals`, `delete_goal` (confirm first). Progress tools refuse habit-linked goals and point Claude at `set_habit`.
  - Both are found by id or title in the current periods: exact title, then part of a title, then the most shared words ("finish problem sheet" → "Problem sheet 4"). Several matches is an error that lists them, so Claude asks.
  - The prompt tells Claude that "today's goals" / "this week's goals" mean to-dos, since goals have deadlines, not days or weeks.
- **Confirm-first:** anything that deletes data or overwrites/trims other data returns `Result(pending=Pending(summary, run))`. The UI shows Confirm/Cancel, and `run()` re-runs the tool with `confirmed=True` against current data.
- **Chat UI:** the bar is fixed to the bottom of the main column on every page except Home, where it's an inline box with the latest reply under it and the full history in a pop-up.
- **Flow:** callbacks set `chat_busy`. `chat.render()` draws first, does the slow work (transcribe, then Claude) and then calls `st.rerun()`, so changes show immediately.

## 8. Startup and smoothness

- **Two windows:** `desktop.py` shows the splash at once, then loads the app in a **hidden** window. When the page renders its `#venato-ready` marker (and at least 2 seconds have passed), it shows the app window and closes the splash.
- **Marker placement:** the marker comes before the Outlook autosync, so the network never delays startup.
- **Global CSS first:** `app.py` sends all global CSS as its first element (top padding, sidebar nav, no stale-element dimming, and hiding the marker's gap). Pages must not inject their own top padding.
- **Toolbar:** `.streamlit/config.toml` sets `client.toolbarMode = "minimal"`, along with `server.address = 127.0.0.1`, XSRF protection and no usage statistics.

- **Fragments:** busy widgets are `@st.fragment`s, so a click reruns just that widget: Home's to-dos (`todos.render_home`), habit ticks (`daily_log._home_habit_rows`, `_habit_ticks`), the Daily Log's day card (`_day_card`: calendar, card, habits, form), the Focus timer (`focus.render_home`, `_page_timer`), Review's charts (`stats._charts`) and weekly reviews (`review.history`).
  - After saving, a fragment's callback calls `kit.rerun_app_if(changed)` with tags (`habit:<id>`, `todo:<id>`, `actual`, `undo`, `page`); it reruns the whole app only if something outside the fragment shows the change (a goal counting that habit, today's Actual, the Undo bar, the Focus page's totals). Call it last: `st.rerun` stops the callback. Add a tag (and a rule in `kit.app_depends_on`) when a new fragment's writes show elsewhere.
  - A fragment can only draw into its own container, and its arguments are reused on its own reruns: read anything that changes (today, settings) inside it. A button inside a fragment that changes the page (`page`) needs an app rerun; keep such buttons outside (Home's habits "Manage").
  - Tests: AppTest's `.run()` always reruns the whole app; `tests/fragment_run.py` runs an interaction as the browser does (just its fragment) and fires component triggers. `st.session_state["home_draws"]` counts full Home draws.

- **Cache rules** (`venato/cache.py`): wrap a read in `@cached` (`kit.cached` is the same) and it is remembered until the data changes. The key is the database path, `store.data_version()` (up on every write through `store.db()`, `save_settings` and `undo.restore`), settings.json's mtime and size, and today's date. So:
  - Only cache reads that depend on the database, settings and today. Anything that reads the clock beyond the date, the network or a file elsewhere (the Outlook cache, `.ics`) must not be cached, or call `store.bump_version()` when it changes.
  - Return picklable data (lists, dicts, DataFrames), never connections. Callers get a copy and may change it.
  - A write that bypasses `store.db()` (another process, a file copy) must call `store.bump_version()`; writes by another process are not seen.
  - Tests that write to the database directly and then read through a cached function should do it through the store, or the cache serves the old answer.
- **Timetable op acknowledgements and rollback:** the grid is local-first: it applies an op in the browser at once and keeps it pending (replayed over incoming data) until Python acknowledges its `opId` in `data.acked`. `_on_ops` acknowledges every op, saved or not. One Python could not save (a locked Plan, or an exception) is acknowledged with the reason in `data.rejected`; the JS drops that op, the block goes back to what was saved, and the reason shows over the grid for a few seconds. Never skip the acknowledgement for an op you refuse: the grid would resend it forever.

## 8b. Installers (`packaging/`, `.github/workflows/release.yml`)

- **Slimmer bundle:** `venato.spec` leaves out the parts of pyarrow Streamlit never loads (parquet, flight, dataset, acero, substrait, gandiva and their libraries). Plotly is not a dependency any more: charts are Altair, which Streamlit already brings. If a new feature imports a pyarrow part that was excluded, `--check` draws a table through pyarrow to catch it. Measurements: `docs/perf.md`.
- **One PyInstaller recipe** (`packaging/venato.spec`) builds `dist/Venato/Venato.exe` on Windows and `dist/Venato.app` on macOS, with Python and every package inside. `app.py`, `.streamlit/config.toml`, `assets/` and the components are data files; `collect_all` picks up packages with data/plugins (Streamlit, keyring, pywebview, the SDK with its bundled CLI, faster-whisper…).
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
- **No `%-d` (or other `%-x`) in Python date formats:** Windows' `strftime` doesn't support them. Use `x.day` instead. (Altair's `format` / `labelExpr` are fine; they run in the browser.)
- **Accessibility in the components:** the custom parts are keyboard-usable and labelled: to-do titles are focusable (Enter edits, Menu key / Shift+F10 opens the menu, Alt+↑/↓ reorders), the timetable has a hidden-until-focused list of its blocks (`renderBlockList`). Keep new interactive bits focusable with an `aria-label`, and keep focus where it was across redraws.
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
