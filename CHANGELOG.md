# Changelog

All notable changes to Venato are listed here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Versions match the git tags and [GitHub Releases](https://github.com/spencertomj1-hue/venato-app/releases).
Venato was called **Arete** up to 1.1.1.

## [Unreleased]

### Added
- **Your sleep today** on the Timetable's side panel. Until today has them, it asks what time you woke up and went to bed (to the half hour). Adding them fills **Sleep** blocks from the start of the timetable day to when you woke, and from bed time to the end of the day, in free time only, so nothing of yours is overwritten. Each can be added on its own (wake-up in the morning, bed time later), and the widget goes once both are in.
- **Setup's last step explains how each day works**: Plan, the Plan locked and copied into the Actual when the day starts, then Confirm at the end. Review and goals only count confirmed days, and setup now says so.
- **Setup offers a calendar to everyone.** People not at uni get a "Connect your calendar" step (one Outlook, Google or iCloud link, no Canvas) so their events show on the timetable and planning goes round them.
- **Place Home tiles anywhere.** In Edit Home a faint grid shows Home's cells, with a spare row underneath, and a dragged tile snaps to the cell under it: any column, any row, leaving gaps if you like. A tile you drop it on swaps into the place it left when it fits there, otherwise it moves to the nearest free spot, and you see where everything will go while you drag. Resizing keeps the tile's top-left corner and moves only what it grows over. Your current layout looks the same until you first change it. In windows under 1000 px wide tiles still stack in reading order.
- **New logo**: a white serif V on a red rounded square, now the app icon (Dock, Windows shortcuts, browser tab) in place of the Greek bust. The loading screen shows it with "Venato" and "BETA" underneath (the motto is gone) on the app's paper colour, and follows dark mode.
- A small **Send feedback** link in the bottom-right corner of every page (setup too), above the chat bar when it's there. It opens the same pre-filled form as Settings → About.
- **Setup asks for your goals first.** Goals is now the step right after Welcome, for everyone, and each row makes a long-term goal: what it is, how long (3, 6 or 12 months, or an end date), how you'll know (**Hours a week** or **A number** puts one target under it, due when the goal ends; **Tick it off** sets just the goal), and, folded away, why it matters and a first step (a to-do on this week's list, under the goal). Going back and pressing Next changes the same goal, target and to-do; emptying a row removes only what setup made for it. What would you track? suggests per goal, and a habit picked for a goal without a target becomes a target under it (three times a week). Students start with a "Do well this term" goal (3 months, editable, removable) and their modules' study-hours targets go under it. Your first week's sittings are named after each goal's target, or the goal. Home gets the Goals tile when you've set any goal.
- **Goals are now long-term plans** over 3, 6 or 12 months (or to any end date), each with a "why". Under each goal sit its **targets** (what goals used to be: measurable, with a deadline, counted by hand, from a habit or from timetable hours, with the same pace charts) and its **to-dos**. The Goals page shows a card per goal with an overall bar (the average of its targets, or its to-dos done when it has no targets) and opens to its targets and to-dos; targets under no goal are listed apart. Home's Goals tile shows your goals with each one's next target. The Timetable's "Give it time" panel lists to-dos and targets under the goal they serve. On the To-dos page, categories under a goal come first (a target's says which goal). Claude can add, list, change and archive goals and put targets and to-dos under them. Goals export and import as their own CSV (Settings → Data). Your existing goals become targets under no goal; nothing else changes.

### Changed
- Workouts has no preset exercises any more. Type any exercise in Add sets; once typed it's saved and offered again next time (its type and muscle group are guessed from the name, e.g. "Bench press" counts as Chest). Unused presets from before are removed once; ones you've used stay.
- Workouts' plan maker is five numbered steps: get Claude to write the plan, paste it, check the sessions, choose when, add them to your timetable. Only the session names ("Push", "Legs") go in the timetable, not the exercises; those stay in the plan, ready to start from the Log tab.
- Timetable: deadlines are small red flags on the grid at the time they're due (the end of the day if they have no time), not chips above the days. The red "now" line only crosses today's column.
- Edit Home: each tile has a grip in its bottom-right corner. Drag it to change the tile's width and height (it snaps to the sizes that tile comes in, the others making room as you go); a tap still steps to the next size.
- Timetable: the "Plan this week" panel is replaced by **Give it time**: your open to-dos and goals. Pick one, then drag (or click) on the week to put it in. A to-do is scheduled where you press, the same as dropping its chip (its own length, ticked from either side). A goal stays picked for more sittings: hours goals count the time straight away, goals counted by hand go up one when a sitting is marked Done.
- Network is back as an optional block (Settings → Blocks): people, groups and who they work for, the times you met or spoke to someone, search and the weekly review.
- With Network on, the timetable gets a **Meetings** category (once you have a category of your own). Blocks and calendar events called things like "Call with Nina", "Coffee - Sam" or "Meeting" go in it. Marking one Done logs it on that person's Network card ("Meeting: Call with Nina"). If the title names nobody in your network, a pop-up asks who it was with (pick people or add someone new). Marking it Not done, or clearing the mark, takes the log back off. Deleting Meetings is respected: it isn't made again.
- Edit Home is plain drag and drop: drag a tile and the others make room as you go, and it lands where you let go (Esc cancels). The pick-up button, arrows and "Drop here" slot are gone; a ⤢ button on each tile steps through its sizes, and the − buttons are smaller. Home's edits no longer show the Undo bar (⌘Z / Ctrl+Z still undoes the last one).
- New icons for the built-in blocks (Timetable, Goals, Focus, Modules, Review, Daily Log): one stroke set, on Home's tile headers and the shortcut tiles at the top of each page. Focus is teal now, not grey. Home's tile icons are square again, not squashed.
- To-dos: the category filter now works on every tab (Today, This week, This month too), so you can see only one category's to-dos, e.g. just Nina's. A to-do added while a filter is on goes in that category. A new **By category** tab lists every open to-do under its category.
- Each goal you set (e.g. "Get a job") is also a to-do category, marked with a flag. Renaming the goal renames it. Deleting the goal keeps the category and its to-dos. Goals already running get their category once, on update.
- Home's timetable shows the whole day (07:00–01:00 by default) with no scrolling, in a new **Column** tile size (one column wide, three rows tall) that it starts in. A saved Tall timetable stays Tall. Its sync and Outlook buttons sit in its title line. Short blocks are a colour bar (the name is in the tooltip).
- Home's Focus tile is a dial. Idle, its ring fills to today's focused time against a daily aim (4 h by default, Focus → Settings); type what you're on and press the dial to start a stopwatch. Running, the ring sweeps once an hour round the time, with the name and start time beside it; press it to stop, which puts it in today's Actual. The dial sizes itself to the tile. Pomodoro timers start on the Focus page.
- Small glances on Home's tiles: Journal shows the week as dots and a streak from 2 days; Daily log puts each habit's streak after its name ("Exercise · 5"); Deadlines' countdowns are coloured pills (red overdue or today, amber within 3 days, grey later); Review has day letters and a faint 100% line.
- Home's Grades tile is now **Modules**: this week's study hours per module against its hours-a-week target, and "4 of 12 h this week" in its header. No marks for now.
- A student's Home starts with Modules in a fourth row, and Home's rows can now be shorter (108px), so all four still fit a 1280×720 window. A tile shows only the rows that fit: one that would be cut off at the bottom is hidden whole.
- Home is the only way round the app: the sidebar is gone. Every tile opens its page (click anywhere on it; ticking a to-do or starting Focus still works in place), and each tile's header has a coloured icon, its name and a short status ("4 behind", "Next: Lunch at 13:00"). Every page has a top bar with "← Home" (Esc does the same) and shortcut tiles to the other pages. Settings is the gear on Home, search / Ask is the bar at the top of Home, and pages have addresses (`?page=goals`), so links and the browser's Back button work.
- Edit Home (was Arrange): a four-column grid of Small, Wide, Large and Tall tiles. − removes a tile (its data stays), tap or drag to move one, the picked-up tile gets a size picker and a drop slot, and "Add a tile" lists what's hidden. Your old layout is converted the first time Home draws.
- A To-dos page with Today / This week / This month tabs (the To-dos tile opens it).
- Home fits on one screen on a laptop (1280×720 and up): the rows share the window's height and each tile shows a summary, with the rest one click away. The timetable runs down the left (see Column above), without a second date. To-dos shows 3 and "+N more" with a smaller Daily / Weekly / Monthly switch, and comes Small or Wide. Goals shows the top 3 (behind ones first), each a name and a thin bar on one line, then "and N more". Needs you shows 3 things on one line each and "+N more"; tap it for everything, with goal bars and Plan my goals. Daily log ticks habits in one line. Narrow windows and phones still scroll. Saved layouts keep their sizes; the new layout is for new installs and Reset.
- Edit Home: each tile's title and Move button share one line, and "Drop here" adds a row under the grid instead of squeezing it.
- To-dos on the timetable: to-dos that aren't scheduled show as chips in their day's header (today's list on today, a to-do with a due day on that day). Drag one onto the grid to schedule it, as long as it takes (30 min if not set). A scheduled to-do's block has a to-do badge. Ticking the to-do, from the chip, the To-dos page, Home or Claude, marks its block done, and marking the block done ticks the to-do. Scheduling it again moves it. Claude can schedule a to-do too.

### Fixed
- In dark mode, red buttons have dark text (white on the light red was too faint to read).
- No grey ring left behind after Esc. Esc (and the browser's Back) now put focus on the page's heading, without a ring; Tab carries on from there and still shows one.
- Leaving a page with Esc or Back fades like the Home button does, instead of the old page's pieces swapping out in front of you, and coming back to Home no longer glides the tiles in from old places (only moves in Edit Home glide).

### Added
- A blank slate. A new install has no categories, activity defaults, habits or goals; the old defaults are now examples that setup suggests. With no category, the Timetable, Goals, Focus and Review show an "Add a category" prompt, and calendar events are grey. Existing installs keep what they have.
- Modules for students. Each module has its own timetable colour (group "Modules"), a card on the Modules page and a page of its own: this week's lectures, deadlines, assessments, study hours and Fit time. Deleting a module only unlinks things.
- Canvas and uni timetable feeds. Paste a published Outlook timetable link and Venato finds your modules; paste a Canvas Calendar Feed and its assignments become deadlines with a due time and a module. A deadline you edit stays as you left it, and one you delete doesn't come back on the next sync.
- Plan a deadline. A deadline's **Plan** books hours for it as an hours goal that finishes the day before it is due, so pace, sittings and "can't make it" all work for it.
- The Daily Log is a journal: it leads with the day's box and prompt, and the calendar marks days you wrote. Sleep and water are optional (Settings → Daily Log). Mood, energy and productivity are gone from the page, stats, review, assistant and CSV; the old columns stay in your database, untouched.
- Home is a grid you arrange (Arrange, top right). Needs you gathers days to confirm, goals behind or short, deadlines this week with no plan, and one-off cards.
- Setup is a short wizard. Students: Welcome (with "Are you at uni?"), Connect your calendars, Your modules (with hours a week), Your goals, What would you track?, Your first week. Everyone else: Welcome, Your goals, What would you track?, Your first week. Every step but Welcome can be skipped, Next and Skip both save what you've typed, Skip setup leaves a blank app, and running it again (Settings → About) only adds things and leaves Home as you arranged it.
- Send feedback: a link in Settings → About opens a short form in your browser with your version and system filled in. Nothing is sent from the app. After 14 days Needs you asks once, "How's Venato treating you?" (Send feedback / Not now). The form's address is `feedback_url` in `venato_config.json`.
- The assistant's add_deadline and edit_deadline take an optional due time (HH:MM).

### Fixed
- `scripts/seed_demo.py` runs again, on the blank-slate schema, with modules, a planned deadline and a journal; a test runs it.
- Search no longer lists the closed plan goal of a deadline you've finished.
- Needs you: "N h to plan" no longer overlaps the goal's bar, and a goal made in the last week with nothing done says "Needs a plan" rather than "Behind".
- Setup reads your connected calendars once instead of on every click, and pasting a link that's already connected says "Already connected" instead of showing an error.
- Only titles made with `kit.subhead` get the serif subheading style; before, any paragraph with one bold word in it did.

### Removed
- Money and Workouts. Their data stays in your database, untouched; nothing is deleted or dropped, it just isn't shown or searched any more.

### Changed
- Home is a grid you arrange, like a phone's home screen. Press the Arrange button (top right), then tap a widget to pick it up and tap another to drop it there, or use each widget's bar: smaller / bigger, back / forward, hide. "Add widget" brings back hidden ones (Deadlines, Goals, Habits, Journal, Focus, Grades); Reset goes back to the start. Moves glide into place, every change saves at once and can be undone. Your Home starts as today's timetable beside Ask, Needs you and To-dos.
- Needs you gathers everything that wants something from you: days to confirm, goals behind or short, deadlines this week with no plan yet, and (once, a week in, with the assistant off) where to switch the assistant on. Nothing to do: "Nothing needs you. Go touch grass."
- Search moved to the top of the sidebar, on every page.
- Home is simpler ("Essentials"): today's timetable on the left, now taller (it fills the window, still without scrolling); on the right Ask Venato, Needs you this week (each goal with its progress bar and how far off today's pace), To-dos and Deadlines. To-dos are one card with a Daily / Weekly / Monthly switch instead of three side-by-side lists. The Agenda list and the separate Goals card are gone (the timetable and Needs you show the same), and widgets with nothing to show (no habits, no marks, no deadlines, Focus with nothing today) aren't drawn.
- Timetable: half-hour blocks show their name centred on one line, never cut off.
- Review has a new one-screen weekly layout (fits a 1440×900 window without scrolling):
  - A ‹ week › stepper and a Week | Trends switch at the top; Trends holds the charts over a period and the last 8 weeks.
  - Left: the week's verdict, a nudge for days not confirmed (Confirm / Check), and Looking back: last week's promise ("Did you?"), your two reflections and the week's journal behind a link.
  - Middle: Goal pace, and a new **Next week** card: deadlines, how much is planned so far, goals that still need time booked, and a Plan next week button that opens the Timetable on next week.
  - Right: time planned vs done per category, with a tick at the target, the shortfall hatched and anything over it in green.
  - The Sunday pop-up shows the same three columns.
- The weekly review opens with a one-line verdict, shows what you said you'd do differently last week and asks whether you did, names the biggest planned-vs-done gaps and flags days that are over but not confirmed. An **Ask Claude** button gets Claude's take in the chat.
- The Sunday pop-up only counts as seen once you press Done or save your answers. Closed by accident, it comes back next time.

### Removed
- Food, Recipes, Cut down, Health data, Involvement, Applications and Network are gone from the public app, so Venato can focus on student life. Your data in them stays in your database, untouched: nothing is deleted or dropped, it just isn't shown or searched any more, and new installs don't create those tables.
- The defusedxml dependency (it was only used to read Apple Health exports).

### Changed
- Code layout: the data layer (`venato/store/`) and Claude's tools (`venato/tools/`) are now packages with one module per area, instead of two files of 2,300 and 1,300 lines. Nothing changes in how Venato works or in your data.
- Faster: Home goes from about 410 ms to about 100 ms per rerun, Goals from 430 to 120 ms, the Timetable from 250 to 140 ms and Review (was Stats) from 290 to 170 ms (demo data, server-side time; see `docs/perf.md`). Reads are remembered until your data changes. Ticking a to-do or a habit that no goal counts (a habit a goal counts reruns the page, as the goal's bar moves), starting or stopping Focus, changing a day in the Daily Log and changing Review's period now redraw just that part of the page (a to-do tick went from about 450 ms to 9 ms, a Focus start from 507 to 17 ms). The timetable grid already moved blocks at once; if a change can't be saved (a started day's locked Plan, or an error) the block now goes back and says why.
- Charts are drawn with Altair, which comes with Streamlit, instead of Plotly. Plotly is no longer a dependency.
- Smaller app: the installers leave out parts of pyarrow that Streamlit never loads (Linux bundle 1014.5 MB to 959.3 MB). The speech model and assistant packages are still bundled.
- Every block can be switched off, Timetable, Goals, Focus, Grades and Review included; a new setup starts with those five on. Daily Log, Money and Workouts are switched on in Settings → Blocks; setup doesn't ask about blocks. Setup is shorter. Stats is now called Review.
- Timetable: the Plan is locked in when a day starts, and the day is changed in its Actual. Before a day starts, whatever is on it is the Plan. When it starts the Plan is locked (that's what Plan vs Actual compares against) and copied into the day's Actual; from then on you move, stretch, delete or add blocks freely and only the Actual changes. At the end of the day you confirm it (Confirm under the day, or Home's "Is the timetable right for today?"), so the day you actually had is the one you acknowledged; only confirmed days count in stats and goals, and nothing is confirmed for you. A Plan / Actual switch on the timetable shows either one (days that haven't started show their Plan in both; a locked Plan is view only, marked "Locked"). The "Timetable view" setting (one timeline / Plan and Actual) is gone, and so are the assumed / skipped / unplanned pieces and the Didn't happen / Change times / Did something else card. Reminders follow today's Actual. The assistant changes a started day's Actual, never its locked Plan.
- Timetable: the Plan looks like a plan. It's drawn as a blueprint (pale blocks outlined in the category colour, on light blue graph paper) wherever it shows: the Plan view, and days that haven't started (tagged "Plan"). What you did stays solid. In the Actual view, where a day didn't go to plan, the Plan shows as a faint outline behind it ("Planned: Gym 18:00–19:00"). The key is in the (?) panel. Switching Plan / Actual is instant (no reload, no flash).
- Timetable: pointing at a block selects it with a thin red outline (⌘/Ctrl+C copies, ⌘/Ctrl+V pastes where you point, Backspace deletes, a click shows its details), its top and bottom edges are easier to grab for stretching or shrinking either way, and the details card and the Plan / Actual switch fade in.

### Added
- Timetable: Confirm under a day is there any time once the day has started, and a confirmed day has an Undo next to "Confirmed": it goes back to assumed as planned (the Plan copies confirming made are removed; Actual blocks you added stay).
- Goals: deadlines instead of months and years. A goal runs from the day you set it to a deadline you pick on a small scrolling calendar, with markers on 2 weeks from now, the end of the month, a month from now, the end of the year and a year from now, and "End of the year" / "In a year" shortcuts under it. Goals past their deadline fold into "Past goals". Deadlines read as numbers ("by 31/12", the year as two digits when it isn't this one: "by 04/01/27"). "Already made progress?" (folded away in the new / edit goal form) counts from a day you pick: a habit's ticks and timetable hours from then count by themselves (with a preview), and a goal kept by hand takes how much you did in that time. The assistant's edit_goal takes `start`. Existing goals keep their month's or year's last day as their deadline. The assistant's add_goal / edit_goal take `due`.
- Timetable: "Confirm all (N days)" confirms every past unconfirmed day that has something on it, in every week, after a preview. The assistant can do the same (`confirm_all`).
- Timetable: one timeline. Plan once; time that has passed shows what happened. A day is assumed to have gone as planned (drawn faded and dashed, with "?") until you confirm it: Confirm under the day, "Confirm week as planned" (with a preview), or Home's end-of-day prompt "Anything not go to plan today?" (All as planned / Review; also for yesterday). Click a passed block for Didn't happen, Change times (or drag its edges) or Did something else; drag across empty passed time to add something unplanned. Skipped blocks are hatched and struck through, unplanned ones outlined, with a text equivalent in the keyboard block list. (The side-by-side Plan and Actual view that was kept at first has since been replaced by the Plan / Actual switch; there is no Timetable view setting.)
- Timetable: suggested sittings. When hours goals are short this week, the grid draws where Plan my goals would put their time as dashed blocks in free gaps (never in the past, never over anything). Click one to add just that sitting; "Add all to Plan" (with a preview) or "Dismiss" (for that week); "Show suggestions" turns them off. The keyboard block list reads them out ("Suggested: Study 16:00–18:00").
- Timetable: a "Plan this week" panel beside the grid (under it on narrow screens): free hours per day, each hours goal's week as a bar with "Fit N h", Plan all goals, Share hours and I'm away for each day. It replaces the goal chips above the grid.
- Timetable: on a week that's over, the panel becomes "How the week went": each goal's "done X of Y h" with ✓ hit, ✕ missed by N h, or, while some days aren't confirmed, "⚠ N h short so far" and "3 days not confirmed: confirm them to count their hours".
- Goals page: a pace chart on each goal's card (Actual so far, even pace, "at this rate", today; it reads its numbers out to screen readers), with the state badge and short detail lines including the goal's own week ("This week 7.5 / 12 h done or planned · 4.5 h short"). A side panel shows "Where this week's N h free go" (one bar split by goal, plus Unclaimed, with Plan my goals and Share hours) and the "can't be finished in time" cards. The "This week's time" bars panel is gone (the same numbers were shown twice).
- Home: today's timetable is always one timeline (what happened before now, the Plan after). A "Needs you this week" card lists only goals that are behind or short, each with its pill and "N h to plan", and Plan my goals. The Goals card gives each goal one status line under its bar ("⚠ Behind: 4.5 h under today's pace"); to-dos sit in a matching card.
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

### Fixed
- Timetable (one timeline): a block no longer gets chopped where time has passed. The part of a block that's already happened and the rest of it are drawn as one block, and runs of the same activity (e.g. Sleep that overran its plan) stay one block. Today shows no "?", Confirm or "Not confirmed" until the day is over.

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
- Timetable: days that haven't happened yet no longer show as Confirmed. Upgrading marked every day with an Actual block confirmed, future ones too; those are cleared on the next start, and a day that hasn't started can't be confirmed (nor by filling in its Actual in the side-by-side view).
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
