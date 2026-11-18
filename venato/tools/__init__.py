"""
The actions Claude can take in Venato, as plain Python functions.

assistant.py exposes each one as an MCP tool; the tests call them directly.
They only use the store, so the rules are the same as the app's pages.
Blocks (venato/blocks) bring their own tools; these are the core ones, by domain:

    common       Result / Pending / ToolError and the input helpers every tool uses
    daily_log    the daily log, habits, stats
    timetable    categories, blocks, confirming days, plan_time
    deadlines    deadlines
    todos        to-dos
    goals        goals and their progress
    journal      the journal
    review       the weekly review
    goal_time    goals on the timetable: pace, the week's budget, planning goal time

Callers use `tools.x` as one module: this file re-exports them all.

Anything that deletes data, or overwrites/trims existing data, doesn't run
straight away: it returns a Result with a `pending` preview. The chat panel
shows that preview with Confirm / Cancel, and Confirm calls `pending.run()`,
which re-runs the same tool with confirmed=True (so it re-checks the data).
"""

from venato import facade

from .common import FILLER_WORDS, PERIOD_NAMES, Pending, Result, ToolError, _now, nice_day
from .daily_log import (add_habit, delete_habit, get_stats, list_habits, log_day, query_entries,
    rename_habit, set_habit, set_habit_target)
from .timetable import (OUTLOOK_PREFIX, add_block, confirm_all, confirm_day, delete_block, describe_block,
    edit_category, list_categories, plan_time, query_blocks, set_activity_default, set_outlook_category,
    skip_block, update_block)
from .deadlines import (add_deadline, complete_deadline, delete_deadline, describe_deadline, edit_deadline,
    list_deadlines)
from .todos import (_find_todo, add_todo, complete_todo, delete_todo, describe_todo, edit_todo, list_todos,
    todo_list_name, uncomplete_todo)
from .goals import (add_goal, delete_goal, describe_goal, edit_goal, list_goals, log_goal_progress,
    set_goal_progress)
from .journal import read_journal, write_journal
from .review import save_review_answers, weekly_review
from .goal_time import goal_pace, goal_spots, plan_goals, resolve_goal, week_budget


# `tools._now = fake` (tests) reaches the submodules that use it (see venato/facade.py).
facade.install(__name__)
