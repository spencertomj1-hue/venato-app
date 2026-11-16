"""
This copy's own blocks (added on top of the shared app, as blocks/__init__.py intends):
To-dos page, Joint calendar, Training (Home: today's session and Km run), and Start Working's
hourly delegation nudge at the top of Home. Start Working itself is the green sidebar button
(ui/work.py), not a block. Also adds this copy's Stats sections (ui/my_stats.py).

Their tools are in assistant.TOOL_SPECS already, so these only describe pages and Home widgets.
"""

import streamlit as st

from venato.blocks import Block


def _todos_page():
    from venato.ui import todo_page
    todo_page.render_page()


def _joint_page():
    from venato.ui import joint_ui
    joint_ui.render_page()


def _training_page():
    from venato.ui import training_ui
    training_ui.render_page()


def _training_home():
    from venato.ui import training_ui
    training_ui.render_home()
    training_ui.render_home_km()


def _nudge_home():
    from venato.ui import work
    question = work.delegate_question()             # the user's own, a new one every hour
    if question:
        st.html(work.nudge_html(question))


BLOCKS = [
    Block("work_nudge", "Delegation nudge", ":material/group:",
          "A question about delegating at the top of Home, a new one every hour (from Start Working).",
          group="Study & work", home=_nudge_home, order=1, default=True),
    Block("todo_page", "To-dos", ":material/checklist:",
          "Every to-do with a due day, your own to-do categories and how long it takes, sorted by urgency.",
          group="Plan", page=_todos_page, order=15, default=True),
    Block("joint", "Joint calendar", ":material/calendar_month:",
          "Your week next to your partner's: busy times from both calendars.",
          group="People & life", page=_joint_page, order=16, default=True),
    Block("training", "Training", ":material/directions_run:",
          "A half-marathon training plan to tick off, runs from Strava, and km run against the plan on Home.",
          group="Health & body", page=_training_page, home=_training_home, order=35, default=True),
]


def _add_stats():
    from venato.ui import my_stats, stats
    if my_stats.render not in stats.EXTRAS:
        stats.EXTRAS.append(my_stats.render)


_add_stats()
