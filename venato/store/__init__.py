"""
Data layer for Venato: every SQL query lives here. No Streamlit code, so the
pages, the Claude tools and the tests all share the same logic.

All user data lives in the data folder (system.default_data_dir(): ~/Library/Application Support/Venato
on a Mac, %APPDATA%/Venato on Windows, ~/.local/share/Venato on Linux), or $VENATO_DATA_DIR, used for tests and the demo). The database is life.db
there (or $VENATO_DB). Backups, settings.json and the Outlook cache live there
too. Nothing user-specific is kept in the project folder.
"""


import pandas as pd

from venato import facade

from .database import (KEEP, _read, bump_version, data_dir, data_version, db, db_path, use_db_path)
from .settings import (DAY_END, DAY_START, MIN_DAY_HOURS, ai_enabled, day_hours, day_length, load_settings,
    save_settings, settings_path)
from .dates import (WEEK_START, _as_date, computer_zone_name, end_of_period, fmt_day, local_now, local_today,
    period_title, set_week_start, shift_period, stamp, start_of_period, tz, week_start_name, week_start_of,
    zone_name)
from .grid import (BLOCK_COLS, TRACKS, apply_block_ops, blocks_for, first_min, get_block_in, plan_paint,
    slot_count, slot_of, slot_time)
from .categories import (DEFAULT_CATEGORIES, DEFAULT_LABEL_MAP, DEFAULT_OUTLOOK_CATEGORY, groups,
    load_categories, load_label_map, outlook_category, remove_label_default, resolve_category, save_category,
    set_label_default)
from .outlook import (OUTLOOK_COLS, _as_block, _detach, _visible_outlook, detach_outlook, get_outlook,
    hide_outlook, outlook_between, outlook_details, outlook_overlaps, outlook_signature, replace_outlook)
from .timetable import (blocks_between, delete_block, get_block, move_block, paint, preview_paint,
    set_block_label, upsert_blocks)
from .days import (confirm_day, confirmed_days, correct, day_ended, day_started, day_status, free_runs,
    live_track, lock_day, lock_started, mark_confirmed, materialise_ops, retime, slots_gone, unconfirm_day,
    unconfirmed_days, unconfirmed_days_with_blocks)
from .journal import (append_journal, entries_between, get_entry, get_journal, journal_entries, save_entry,
    save_journal)
from .habits import (HABIT_PREFIX, add_habit, delete_habit, find_habit, get_habit_dates, get_habits,
    habit_progress, habit_targets, habit_ticks_between, rename_habit, set_habit_done, set_habit_target,
    streaks, week_ticks, weekly_streaks)
from .history import (_clean, _is_ticked, load_all_data, save_all_data)
from .deadline import (DEADLINE_COLS, add_deadline, countdown, deadlines, delete_deadline, get_deadline,
    set_deadline_done, update_deadline)
from .todos import (TODO_COLS, TODO_PERIODS, add_todo, carry_over, delete_todo, get_todo, load_todos,
    move_target, move_todo, reorder_todos, roll_todos, save_todos, set_todo_done, todos_for, todos_progress,
    update_todo)
from .goals import (GOAL_COLS, GOAL_PERIODS, _goal_matches, _num, add_goal, add_goal_progress, away_days,
    away_uids, calendar_horizon, counted_between, delete_goal, get_goal, goal_hours, goal_title_due,
    goal_week_hours, goals_active, goals_in, goals_open, goals_overlapping, goals_past, habit_has_goal,
    load_goals, reorder_goals, save_goals, set_away, set_away_day, set_goal_progress, set_goal_week_hours,
    update_goal)
from .review import (get_review, reviews, save_review)
from .stats import (get_stats, period_start)
from .find import (_SEARCH, search)
from .schema import (init_db)


# store.SLOTS / FIRST_MIN / DATA_DIR / DB_PATH: read fresh on every access (see venato/facade.py).
facade.install(__name__, live={
    "DATA_DIR": (data_dir, None),
    "DB_PATH": (db_path, use_db_path),
    "SLOTS": (slot_count, None),
    "FIRST_MIN": (first_min, None),
})
