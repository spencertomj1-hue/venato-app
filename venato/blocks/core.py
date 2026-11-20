"""The blocks Venato started with: timetable, goals, stats (the Review page) and the daily log.
Their pages and tools live where they always have (venato/ui/*, venato/tools/); this just
describes them as blocks. All of them can be switched off; they're on for installs that never chose."""

from venato.blocks import Block


def _timetable_page():
    from venato.ui import timetable
    timetable.render_page()


def _goals_page():
    from venato.ui import goals
    goals.render_page()


def _goals_home():
    from venato import pace
    from venato.ui import deadlines, goal_time, todos
    goal_time.needs_you(pace.Ctx())        # goals behind or short this week: "N h to plan" and their bars
    todos.render_home()                    # one card: Daily / Weekly / Monthly
    deadlines.render_home()


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
          group="Plan", page=_timetable_page, order=10, default=True, core=True),
    Block("goals", "Goals", ":material/flag:",
          "To-dos for the day, week and month, goals with progress bars, and deadlines.",
          group="Plan", page=_goals_page, home=_goals_home, order=20, default=True, core=True),
    Block("log", "Daily Log", ":material/edit_calendar:",
          "A journal for each day, habits with streaks, and optional sleep and water.",
          group="Health & body", page=_log_page, home=_log_home, order=60, default=True, core=True,
          search={"Habit": ("SELECT id, name, NULL, NULL, per_week FROM habits", "name", "name"),
                  "Journal": ("SELECT date, notes, NULL, date, NULL FROM entries", "COALESCE(notes, '')")},
          search_icons={"Habit": "repeat", "Journal": "edit_note"}, search_open=_log_search_open),
    Block("stats", "Review", ":material/monitoring:",
          "Time planned vs done, your past weekly reviews, and sleep charts if you track it.",
          group="Plan", page=_stats_page, order=50, default=True, core=True),
]
