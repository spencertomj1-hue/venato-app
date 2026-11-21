"""
To-dos block: a page with every to-do sorted by when it's due (Overdue, Today, Tomorrow, This week,
Later), the user's own to-do categories with colours, and how long each one takes.
The page is venato/ui/todo_page.py; its tables and SQL are in store.py (the same to-dos as Goals' lists).
"""

from venato.blocks import Block


def _page():
    from venato.ui import todo_page
    todo_page.render_page()


BLOCK = Block("todo_page", "To-dos", ":material/checklist:",
              "Every to-do with a due day, your own to-do categories and how long it takes, sorted by urgency.",
              group="Plan", page=_page, order=15)
