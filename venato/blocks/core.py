"""The blocks Venato started with: timetable, goals, stats (the Review page) and the daily log.
Their pages and tools live where they always have (venato/ui/*, tools.py); this just
describes them as blocks. Timetable, goals and stats are core (always on); the log is optional
but stays on for installs that never chose."""

from venato.blocks import Block


def _timetable_page():
    from venato.ui import timetable
    timetable.render_page()


def _goals_page():
    from venato.ui import goals
    goals.render_page()


def _goals_home():
    from venato import pace
    from venato.ui import deadlines, goal_time, goals, todos
    ctx = pace.Ctx()                       # one look at the timetable for both goal widgets
    goal_time.needs_you(ctx)               # goals behind or short this week, with "N h to plan"
    todos.render_home()
    deadlines.render_home()
    goals.render_home(ctx)                 # every goal: bar, "by today" tick, one status line


def _log_page():
    from venato.ui import daily_log
    daily_log.page_daily_log()


def _log_home():
    from venato.ui import daily_log
    daily_log.render_home_habits()


def _stats_page():
    from venato.ui import stats
    stats.page_stats()


def _log_search_open(r, ss):
    ss["page"] = "Daily Log"
    if r["date"]:
        from venato import store
        ss["log_day"] = store._as_date(r["date"])
        ss["log_month"] = ss["log_day"].replace(day=1)


BLOCKS = [
    Block("timetable", "Timetable", ":material/calendar_view_week:",
          "Your week, with a Plan / Actual switch, Outlook events and Fit time.",
          group="Plan", page=_timetable_page, order=10, core=True),
    Block("goals", "Goals", ":material/flag:",
          "To-dos for the day, week and month, goals with progress bars, and deadlines.",
          group="Plan", page=_goals_page, home=_goals_home, order=20, core=True),
    Block("log", "Daily Log", ":material/edit_calendar:",
          "Mood, sleep, energy and water each day, habits with streaks, and your journal.",
          group="Health & body", page=_log_page, home=_log_home, order=60, default=True,
          search={"Habit": ("SELECT id, name, NULL, NULL, per_week FROM habits", "name", "name"),
                  "Journal": ("SELECT date, notes, NULL, date, NULL FROM entries", "COALESCE(notes, '')")},
          search_icons={"Habit": "repeat", "Journal": "edit_note"}, search_open=_log_search_open),
    Block("stats", "Review", ":material/monitoring:",
          "Time planned vs done, your past weekly reviews, and mood and sleep charts when Daily Log is on.",
          group="Plan", page=_stats_page, order=50, core=True),
]
