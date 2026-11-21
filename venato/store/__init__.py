"""
Data layer for Venato: every SQL query lives here. No Streamlit code, so the
pages, the Claude tools and the tests all share the same logic.

Callers use it as one module (`from venato import store`; `store.add_todo(...)`): this file
re-exports every submodule's public names. Each module only imports from the ones above it:

    database     the data folder, the SQLite connection (db) and the data version
    settings     settings.json, and the timetable day's hours
    dates        time zone, now / today, weeks, and day / week / month periods
    grid         the timetable's half-hour slots, painting rules and raw block rows
    categories   timetable categories and activity -> category defaults
    outlook      imported calendar events on the timetable
    timetable    the user's blocks: paint, move, relabel, read
    days         a day's Plan locked, its Actual adjusted, then confirmed
    journal      the daily log (notes, sleep, water) and the journal
    habits       habits, weekly targets and streaks
    history      the whole log as one table (History, CSV import / export)
    deadline     deadlines
    todos        to-dos per day / week / month
    goals        goals, the week's goal hours, away days
    review       weekly reviews
    stats        the Review page's numbers
    find         search across everything
    schema       creates the tables and migrates older databases

All user data lives in the data folder (see database.py).
"""

from venato import facade

from .database import KEEP, bump_version, data_dir, data_version, db, db_path, use_db_path
from .settings import (DAY_END, DAY_START, MIN_DAY_HOURS, ai_enabled, day_hours, day_length, load_settings,
    save_settings, settings_path)
from .dates import (WEEK_START, _as_date, computer_zone_name, end_of_period, fmt_day, local_now, local_today,
    period_title, set_week_start, shift_period, stamp, start_of_period, tz, week_start_name, week_start_of,
    zone_name)
from .grid import (BLOCK_COLS, TRACKS, apply_block_ops, blocks_for, first_min, get_block_in, plan_paint,
    slot_count, slot_of, slot_time)
from .categories import (EXAMPLE_CATEGORIES, EXAMPLE_LABEL_MAP, DEFAULT_OUTLOOK_CATEGORY, MODULE_COLOURS,
    MODULES_GROUP, add_module_category, event_category, groups, load_categories, load_label_map, next_free_colour,
    outlook_category, remove_label_default, rename_category, resolve_category, save_category, set_label_default)
from .outlook import (OUTLOOK_COLS, _as_block, detach_outlook, get_outlook, hide_outlook, outlook_between,
    outlook_details, outlook_overlaps, outlook_signature, replace_outlook, tag_outlook_modules)
from .timetable import (blocks_between, delete_block, get_block, move_block, paint, preview_paint,
    set_block_label, upsert_blocks)
from .days import (confirm_day, confirmed_days, correct, day_ended, day_started, day_status, free_runs,
    live_track, lock_day, lock_started, mark_confirmed, materialise_ops, retime, slots_gone, unconfirm_day,
    unconfirmed_days, unconfirmed_days_with_blocks)
from .journal import (ENTRY_FIELDS, add_day_tracker, append_journal, day_trackers, day_values, day_values_between,
    delete_day_tracker, entries_between, find_day_tracker, get_entry, get_journal, journal_entries,
    journal_todo_new, logged_rows, save_entry, save_journal, set_day_value, set_entry_field, set_tracking,
    tracks_sleep, tracks_water, update_day_tracker)
from .habits import (HABIT_PREFIX, add_habit, delete_habit, find_habit, get_habit_dates, get_habits,
    habit_progress, habit_targets, habit_ticks_between, rename_habit, set_habit_done, set_habit_target,
    streaks, week_ticks, weekly_streaks)
from .history import load_all_data, save_all_data
from .deadline import (DEADLINE_COLS, add_deadline, countdown, deadline_overdue, deadlines, delete_deadline,
    get_deadline, import_canvas, plan_deadline, set_deadline_done, update_deadline)
from .todos import (TODO_BASE, TODO_COLS, TODO_GROUP_COLOURS, TODO_MINUTES, TODO_PERIODS, add_detailed_todo,
    add_todo, add_todo_group, carry_over, delete_todo, delete_todo_group, done_todos, get_todo, list_for_due,
    load_todos, move_target, move_todo, open_todos, reorder_todos, roll_todos, save_todos, set_todo_done,
    todo_due, todo_groups, todos_for, todos_progress, update_todo, update_todo_group)
from .goals import (GOAL_COLS, GOAL_PERIODS, _goal_matches, _num, add_goal, add_goal_progress, away_days,
    away_uids, calendar_horizon, counted_between, deadline_goal, delete_goal, get_goal, goal_hours, goal_title_due,
    goal_week_hours, goals_active, goals_in, goals_open, goals_overlapping, goals_past, habit_has_goal,
    load_goals, reorder_goals, save_goals, set_away, set_away_day, set_goal_progress, set_goal_week_hours,
    update_goal)
from .review import get_review, reviews, save_review
from .stats import get_stats, period_start
from .find import _SEARCH, search
from .schema import _add_column, init_db


# store.SLOTS / FIRST_MIN / DATA_DIR / DB_PATH: read fresh on every access (see venato/facade.py).
facade.install(__name__, live={
    "DATA_DIR": (data_dir, None),
    "DB_PATH": (db_path, use_db_path),
    "SLOTS": (slot_count, None),
    "FIRST_MIN": (first_min, None),
})
