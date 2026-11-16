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
  quick.py                     Quick commands ("drank 500ml", "tick gym"): handled without Claude via the same tools.py actions
  pace.py                      Goals meet the timetable: capacity, budget, pace, debt, follow-through, negotiation, suggestions (§5e). No SQL, no Streamlit
  blocks/                      Optional blocks (Focus, Workouts, Food, Recipes, Cut down, Grades, Money, Involvement, Health):
                               each has its own tables, migrations, tools, prompt, context and page (core.py: the Block shape)
  voice.py                     Microphone recording (sounddevice) and local transcription (faster-whisper)
  outlook.py                   Read-only Outlook import: link checks, Keychain, fetch, recurrence expansion, sync
  notify.py                    Reminders: a background thread that notifies before Plan blocks / Outlook events start
  updates.py                   Daily check of GitHub's latest release vs venato/VERSION (written by packaging/venato.spec; none = "dev", not checked); banner in app.py
  review.py                    Weekly review numbers (summary, due_week: from 7pm Sunday); ui/review.py shows the pop-up and Stats' history; reflections in `weekly_reviews`
  undo.py                      Undo: whole-database snapshot before deletes / overwrites (ui/undo_bar.py offers it)
  setup_checks.py              Logic behind the wizard/Settings: Claude status, mic test, backups, Finder
  ui/                          One module per page or section (imported as `from venato.ui import goals`, ...)
    search.py                  Home's search box: store.search (every word, any case, per kind) and Open (sets page + day / person)
    timetable.py               Timetable page and the week/day grid's Python side
    timetable_tools.py         Buttons above the grid: Add block, Fit time, Categories (dialogs calling the same tools.py functions as Claude)
    daily_log.py               Daily Log page (month calendar, day card, the day's habits, entry form with the journal box, past entries) and Home's habits
    todos.py                   Home's to-do cards
    goals.py                   Goals page (cards in two columns per section, side panel) and Home's goal bars (with the "by today" tick)
    goal_chart.py              The Goals page's pace chart: an SVG drawn as an <img> (st.html strips inline SVG), alt text with the numbers; legend() once per page
    goal_time.py               Timetable: the "Plan this week" panel (free hours per day, goal bars with Fit N h, Plan all goals, I'm away) and suggested sittings; Share hours; the Goals page's pace lines, offers and suggestions
    deadlines.py               Deadlines section (Goals page) and Home's list, with "Make time"
    review.py                  Weekly review pop-up and Stats' history
    home.py, stats.py          Home (agenda, widgets) and Stats pages
    applications.py            Applications page (apps_component.*)
    blocks_ui.py               Settings → Blocks; one page module per block (focus.py, money.py, ...)
    undo_bar.py, page_fade.py  The Undo bar; the fade between pages
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
| `goals` | `id`, `title`, `period` (monthly/yearly), `period_start`, `target`, `unit`, `progress` (kept by hand), `habit_id` (NULL = by hand; `ON DELETE SET NULL`), `ord` (also its priority), `created_at`, `category_id` (counts timetable hours; `ON DELETE SET NULL`; never together with `habit_id`), `label` (optional: only that activity) |
| `goal_week` | The user's split of a week between hours goals: `goal_id` (cascade), `week_start`, `hours`. None = automatic |
| `tt_outlook_away` | All-day calendar events marked "I'm away" (that day has no free time for goals); kept across syncs |
| `away_days` | Days marked "I'm away" by hand (`date`), no calendar event needed |
| `tt_day_status` | One timeline (§5f): `date` (PK), `confirmed_at` (NULL = not confirmed), `upto` ("HH:mm": the day's Actual is the truth before this). Made by `_day_status_table` on first run, marking every day that already had Actual blocks confirmed |

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
  - A paint carries the new block's id (`newId`), so both sides agree on it.
- **Views:** `render_page` is the week (editable). `render_today` is Home's single day: view only, always one timeline, with rows sized to fit the window (`fitToWindow`) and the key wrapped underneath. `render_grid(view=)` picks one timeline (`"one"`) or Plan and Actual (`"split"`); the default is `store.timetable_view()` (settings.json `timetable_view`; missing = `"one"`, set to `"split"` for installs that already had blocks).
- **Clicking a block** grows it and opens a details card (title, time, category, location, description), with Edit and Delete/Remove buttons except on Home. A drag paints, and a click with the eraser erases.
- **Block text** is black unless the fill is dark (`contrastText`, luminance threshold 90).

## 5b. To-dos and goals

Two different things:
- **To-dos** are tick-off lists for a day, a week or a month, shown only on Home.
- **Goals** are measurable targets for a month or a year, with progress bars, on the Goals page and on Home.

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
- **Goals page:** two bordered sections (Monthly, Yearly), each with ‹ › and a "This month / This year" jump (`goals_start_<period>`). Each goal shows `value / target unit`, a percentage and a bar. Hand-kept goals have − / + (via `add_goal_progress`); every goal has a ⋯ popover to edit it (including the "Update it myself" / "Count a habit's ticks" choice) or delete it. "New goal" is a popover with the same form.
- **Bars:** HTML in the theme's primary colour (`st.progress` uses a different one), the same on both pages.
- **Home:** this month's and this year's goals as bars, with "See all" (a button whose callback sets the sidebar radio, `page`).

## 5c. Network

- **Tree:** You → a hub circle per group (ids `g:<group id>`) → sub-group hubs → people; ungrouped people hang off You. Only groups with someone in them (or below them) get a hub. Tree lines are solid and tinted with the parent's colour; person-to-person links are dashed.
- **Web (`network_component.*`, key `network`):** SVG drawn once per data change; positions come from a small force simulation (repulsion, with hubs and You pushing harder; springs along tree lines, short for people, longer for groups; weak springs for cross-links; a weak pull to the centre; speeds capped). New data is pre-settled for up to 400 steps, then fitted to the frame the first time. Labels scale up when zoomed out (`--label`). Positions, pan/zoom and hidden top-level groups are kept in sessionStorage. A dragged circle stays where it's dropped.
- **Cards and dialogs:** selection is local to the JS. Card buttons send `edit` `{kind: person|group, id}`, `{kind: new_person, group}` or `{kind: new_group, parent}`; `_on_edit` stores it in `net_edit`, and `render_page` pops it and opens the matching `st.dialog` once (clicks inside a dialog rerun only the dialog). Dialog buttons are never disabled: Streamlit text boxes only commit on Enter/blur, so they validate on click instead.
- **Claude:** `add_person`, `update_person`, `connect_people`, `disconnect_people` (confirm), `delete_person` (confirm), `add_group` (with `inside`), `edit_group` (rename/recolour/move), `delete_group` (confirm; its people and sub-groups move up a level), `find_people` (lists groups as a tree). Names aren't unique: lookups match an exact name first, then part of a name, and several matches is an error that lists them. Everyone is implicitly linked to the user, so there's no "me" person.

- **Interaction log:** `net_interactions`, newest first. The person dialog adds/removes entries; the card shows "Last spoke" and the latest 3 (`recent` in the component data). Claude: `log_interaction`, `person_history`; `find_people` shows the last one.

## 5d. Journal and reminders

- **Journal = the day's notes (`entries.notes`):** `get_journal` / `save_journal` / `append_journal` / `journal_entries` work on that column (`save_journal` leaves the numbers alone and drops a row left empty). Databases from when the journal had its own `journal` table get it folded into notes by `_journal_became_notes` (appended unless already there) and the table dropped. In the Daily Log the form's widget keys include a hash of the saved entry, so if Claude adds to the day the box shows it instead of a stale draft. Search is `LIKE` per word (wildcards escaped). Claude: `write_journal` appends a paragraph (replace=true needs confirmation), `read_journal` by day, range and/or words. Settings → Data downloads it as Markdown.
- **Reminders (`notify.py`):** `notify.start()` in `app.py` starts one daemon thread per process (skipped when `VENATO_NO_REMINDERS` is set, as the tests do). Every 30 s `check()` reads the settings, finds Plan blocks and visible timed Outlook events from yesterday's and today's timetable days (times before 07:00 are the next calendar day) that start within `reminder_minutes` (or started under a minute ago), and announces each once (key: date|start|label). `system.notify` runs `osascript` (macOS; shows as from Script Editor), a PowerShell toast (Windows) or `notify-send` (Linux), passing the text as arguments / environment variables so nothing in it runs as code.

## 5e. Goals and the timetable (`pace.py`, `ui/goal_time.py`)

- **One helper:** `store.goal_hours(goal, first, last, track, data=None, window=None)` counts an hours goal's category (and label: exact for blocks, contained in the title for calendar events) in a track. The Plan includes visible timed calendar events in that category; detached ones (`ol:` blocks) never count. `pace.Ctx` reads the blocks and events once per page and passes them as `data`; `window(day)` cuts a day to some slots (`ctx.past` / `ctx.future`).
- **Capacity:** per day, the slots from now on that aren't fixed. Fixed = visible timed calendar events + Plan blocks that serve no hours goal active that day (+ every `ol:` block). Time already planned for a goal counts as free for goals. Past days and away days have none; all-day events don't block. Past `calendar_horizon()` (8 weeks, the sync window) a day uses the average fixed load for its weekday and is flagged `estimate`. Sleep isn't subtracted.
- **Need and debt:** `week_need` spreads what was left at the start of the week (now, for later weeks) over the days left, times the week's days in the period (partial weeks work). Baseline = target × days / period days; need − baseline is the carried debt. Computed, never stored.
- **Follow-through:** Actual ÷ Plan for the goal over the last 6 complete weeks with a Plan, needing 3 of them, clamped 30–100%. `want` = done + rest of need ÷ follow-through (or `goal_week`'s hours). Setting `goal_inflate` (default on) switches the inflation off.
- **Budget / competition:** `week_goals` hands the rest of the week's capacity out top-down by priority (`ord`, monthly first on a tie) as `alloc`; `budget_short` is what doesn't fit. Count goals (books, money) get pace and debt but no budget. Yearly goals are budgeted week by week like monthly ones.
- **Pace states:** done; unreachable (hours: remaining > free time left; habit: remaining > days left); behind (covered < want this week; habit/count: below the even-pace line and late at the trailing rate); slipping (planned enough, but Actual trails Plan this week by 1 h+); on track. Projection: the last 28 days' rate (hand-kept: the period so far).
- **Negotiation:** `negotiation(goal)` when remaining > what the goal can get after higher-priority goals (`available_for`), or unreachable: offers lower / carry / take, applied by `tools.resolve_goal` (a Pending; the UI calls `undo.checkpoint`). `goal_offers_dismissed` in settings.json.
- **Suggestions:** categories / activities with 2 h+ of Actual time in 3 of the last 4 weeks and no goal counting them; dismissals in `goal_suggestions_dismissed`. Categories in `pace.NEVER_SUGGEST` (Sleep, by id or name) are never suggested.
- **Nudge:** `notify.goal_nudges` → `pace.nudges`: from midday on the week's third day, once per goal per week (`goal_nudged` in settings.json, so restarts don't repeat it).
- **Claude:** `goal_pace`, `week_budget`, `plan_goals` (shares free gaps between goals via `tools._place`, the same placement `plan_time` uses), and a line in the [Now] snapshot. Buttons: the planner panel / Plan my goals / Share hours / pace lines.
- **Timetable planner (`goal_time.planner`)**: beside the grid (`st.columns`, so it stacks on narrow screens): free hours per day (`week_capacity`), each goal's bar (`_bar`, CSS once from `bar_style()`) with "Fit N h" (`_fit_goal` → `timetable_tools.open_fit`), Plan all goals, Share hours when over budget, I'm away checkboxes. It replaced the chip strip.
- **Goals page:** each card: badge (`goal_time.badge`), the value, `goal_chart.chart(p, ctx)` (history from `pace.history`: confirmed-day Actual per day, a point a week for yearly goals; even pace dashed grey; projection dotted from today at `p["rate"]`; a today line), then `goal_chart.week_line` + `p["details"]`. Side panel: `goal_time.free_split` (week_budget allocs per goal + Unclaimed, colours `GOAL_COLOURS` validated light/dark with the dataviz checker), `offers`, `suggestions`.
- **Suggested sittings:** `tools.goal_spots(date)` is the placement `plan_goals` uses (so "Add all to Plan" adds exactly what's drawn). `goal_time.suggestions_for(first)` turns it into grid data (`data.suggestions`, ids `sg:<day>:<HH:mm>`); the JS draws them dashed only where the Plan is still free and the slot hasn't passed (`addGhosts`). A click sends `add_suggestion`; Python paints it only if those slots are still free (`goal_time.add_suggestion`). Settings: `show_suggestions` (default on), `suggestions_dismissed` (week starts).

## 5f. One timeline (Plan, corrected into the Actual)

- **Data stays two tracks.** `tt_entries` keeps `plan` and `actual`; only the grid merges them. Review, stats, Focus and the assistant read Actual as before, filtered to **confirmed days** (`store.confirmed_days`).
- **Materialise** (`store.materialise(day, conn, now, confirm)`): copies the day's passed Plan (own blocks + visible timed calendar events, `_plan_items`) into every **empty** Actual slot between the old `upto` and the slots gone by now (`store.slots_gone`), never over an Actual block (Focus, hand-entered). Ids are `m:<day>:<HH:mm>` so the JS mirror agrees. Idempotent. A past day becomes confirmed; today only with `confirm=True`. Calendar events are copied as ordinary blocks; the event itself is never hidden or detached.
- **Corrections** (all materialise first): `store.correct(day, s, e, block|None)` (didn't happen / did something else / unplanned), `store.retime(day, s0, e0, s, e, block)`, `store.confirm_day`. Side-by-side grid edits to the Actual call `store.mark_confirmed` instead (the user's own Actual is the truth; nothing copied).
- **Grid:** `data.view`, `data.dayState[date] = {gone, upto, confirmed}`. In one-timeline mode `cells[d].plan` and `.actual` are the same column; slots ≥ `gone` behave exactly like the Plan column; passed slots are "pieces" (`paintOne`: actual / assumed / unplanned / skipped, never colour alone: ✓ ? + ✕, dashed, outline, hatching). New ops `skip`, `replace`, `retime`, `confirm_day` (opId + ack as usual; `materialiseLocal` mirrors the store). Confirm buttons in the header are `tabindex=-1` (the table is `aria-hidden`); the block list has the keyboard equivalent.
- **Prompts:** Home's `timetable.end_of_day_prompt()`: today once `store.day_ended` (its last Plan item has passed), and yesterday, if unconfirmed; "Not now" stores the date in settings `eod_dismissed`. Timetable toolbar: "Confirm week as planned (N days)" → `tools.confirm_day(..., preview=True)` (a Pending).
- **Assistant:** `confirm_day`, `skip_block`; `add_block` / `update_block` / `delete_block` on the Actual materialise first.
- **Goals (`pace.py`):** `goal_hours(track="actual")` counts confirmed days only (`data["confirmed"]`). `Ctx.hours(days="confirmed"|"unconfirmed")` keeps Plan-vs-Actual on the same days (follow-through, `plan_so_far`/slipping). `week_goals` adds `assumed` (passed Plan on unconfirmed days, included in `covered` so it isn't planned twice), `confirmed_days`, `days_so_far`. The trailing rate is per confirmed day.

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
  - Journal: `write_journal`, `read_journal`. Network interactions: `log_interaction`, `person_history`.
  - To-dos: `add_todo`, `complete_todo`, `uncomplete_todo`, `list_todos`, `delete_todo` (confirm first).
  - Goals: `goal_pace`, `week_budget`, `plan_goals` (§5e), `add_goal` (habit or category/label), `log_goal_progress`, `set_goal_progress`, `edit_goal`, `list_goals`, `delete_goal` (confirm first). Progress tools refuse habit-linked goals and point Claude at `set_habit`.
  - Both are found by id or title in the current periods: exact title, then part of a title, then the most shared words ("finish problem sheet" → "Problem sheet 4"). Several matches is an error that lists them, so Claude asks.
  - The prompt tells Claude that "today's goals" / "this week's goals" mean to-dos, since goals are only monthly or yearly.
- **Confirm-first:** anything that deletes data or overwrites/trims other data returns `Result(pending=Pending(summary, run))`. The UI shows Confirm/Cancel, and `run()` re-runs the tool with `confirmed=True` against current data.
- **Chat UI:** the bar is fixed to the bottom of the main column on every page except Home, where it's an inline box with the latest reply under it and the full history in a pop-up.
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
