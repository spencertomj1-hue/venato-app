"""The blocks Venato started with: timetable, goals, stats (the Review page) and the daily log.
Their pages and tools live where they always have (venato/ui/*, venato/tools/); this just
describes them as blocks. All of them can be switched off; they're on for installs that never chose."""

from venato.blocks import Block, Widget


def _timetable_page():
    from venato.ui import timetable
    timetable.render_page()


def _goals_page():
    from venato.ui import goals
    goals.render_page()


def _timetable_today():
    from venato.ui import timetable
    timetable.render_today()


def _todos_home():
    from venato.ui import todos
    todos.render_home()                    # one card: Daily / Weekly / Monthly


def _deadlines_home():
    from venato.ui import deadlines
    deadlines.render_home()


def _goals_home(size="wide"):
    from venato.ui import goals
    goals.render_home(size)


def _todos_page():
    from venato.ui import todos
    todos.render_page()


def _review_home(size="small"):
    from venato.ui import stats
    stats.render_home(size)


def _st(name, sized=False):
    """A tile's status line, from venato/tile_status.py. sized: it depends on the tile's size."""
    def status():
        from venato import tile_status
        return getattr(tile_status, name)()

    def sized_status(size="small"):
        from venato import tile_status
        return getattr(tile_status, name)(size=size)
    return sized_status if sized else status


def _log_page():
    from venato.ui import daily_log
    daily_log.page_daily_log()


def _habits_home():
    from venato.ui import daily_log
    daily_log.render_home_habits()


def _journal_home():
    from venato.ui import daily_log
    daily_log.render_home_journal()


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
          group="Plan", page=_timetable_page, order=10, default=True, core=True,
          widgets=[Widget("timetable_today", "Timetable", _timetable_today, "column", ("wide", "large", "tall", "column"),
                          status=_st("timetable"), colour="#0B4F9C")]),
    Block("goals", "Goals", ":material/flag:",
          "To-dos for the day, week and month, goals with progress bars, and deadlines.",
          group="Plan", page=_goals_page, order=20, default=True, core=True,
          pages={"To-dos": _todos_page},
          widgets=[Widget("todos", "To-dos", _todos_home, "wide", ("small", "wide"), page="To-dos", status=_st("todos"),
                          icon=":material/check:", colour="#C62828"),
                   Widget("deadlines", "Deadlines", _deadlines_home, "small", ("small", "wide", "tall"),
                          status=_st("deadlines"), icon=":material/event:", colour="#5F6170"),
                   Widget("goals", "Goals", _goals_home, "wide", ("small", "wide", "large", "tall", "column"), status=_st("goals"), icon=":material/flag:",
                          colour="#146C2E")]),
    Block("log", "Daily Log", ":material/edit_calendar:",
          "A journal for each day, habits with streaks, and optional sleep and water.",
          group="Health & body", page=_log_page, order=60, default=True, core=True,
          widgets=[Widget("habits", "Daily log", _habits_home, "small", status=_st("habits"), colour="#B45309"),
                   Widget("journal", "Journal", _journal_home, "small", status=_st("journal"), icon=":material/edit_note:",
                          colour="#B45309")],
          search={"Habit": ("SELECT id, name, NULL, NULL, per_week FROM habits", "name", "name"),
                  "Journal": ("SELECT date, notes, NULL, date, NULL FROM entries", "COALESCE(notes, '')")},
          search_icons={"Habit": "repeat", "Journal": "edit_note"}, search_open=_log_search_open),
    Block("stats", "Review", ":material/monitoring:",
          "Time planned vs done, your past weekly reviews, and sleep charts if you track it.",
          group="Plan", page=_stats_page, order=50, default=True, core=True,
          widgets=[Widget("review", "Review", _review_home, "small", ("small", "wide", "large"), status=_st("review", True),
                          colour="#8E1C1C")]),
]
