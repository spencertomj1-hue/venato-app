"""The blocks Venato started with: timetable, goals, daily log, applications, network, stats.
Their pages and tools live where they always have (venato/ui/*, tools.py); this just
describes them as blocks, on by default."""

from venato.blocks import Block


def _timetable_page():
    from venato.ui import timetable
    timetable.render_page()


def _goals_page():
    from venato.ui import goals
    goals.render_page()


def _goals_home():
    from venato.ui import deadlines, goals, todos
    todos.render_home()
    deadlines.render_home()
    goals.render_home()


def _log_page():
    from venato.ui import daily_log
    daily_log.page_daily_log()


def _log_home():
    from venato.ui import daily_log
    daily_log.render_home_habits()


def _applications_page():
    from venato.ui import applications
    applications.render_page()


def _network_page():
    from venato.ui import network
    network.render_page()


def _stats_page():
    from venato.ui import stats
    stats.page_stats()


BLOCKS = [
    Block("timetable", "Timetable", ":material/calendar_view_week:",
          "Your week in Plan and Actual columns, with Outlook events and Fit time.",
          group="Plan", page=_timetable_page, order=10, default=True),
    Block("goals", "Goals", ":material/flag:",
          "To-dos for the day, week and month, goals with progress bars, and deadlines.",
          group="Plan", page=_goals_page, home=_goals_home, order=20, default=True),
    Block("log", "Daily Log", ":material/edit_calendar:",
          "Mood, sleep, energy and water each day, habits with streaks, and your journal.",
          group="Health & body", page=_log_page, home=_log_home, order=30, default=True),
    Block("applications", "Applications", ":material/work:",
          "A table of jobs, internships and courses you've applied for, with status and deadlines.",
          group="Study & work", page=_applications_page, order=60, default=True),
    Block("network", "Network", ":material/hub:",
          "A map of the people you know, the groups they're in, and when you last met.",
          group="People & life", page=_network_page, order=80, default=True),
    Block("stats", "Stats", ":material/monitoring:",
          "Charts of mood, sleep, energy, water and habits, and your past weekly reviews.",
          group="Other", page=_stats_page, order=90, default=True),
]
