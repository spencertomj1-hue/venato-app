"""
The journal: one page per day (the daily log's notes), written on the Daily Log page.

Writing to-dos into the journal:
  "Buy monitors"   (straight or curly quotes)  -> a to-do in that day's list
  ^Meal prep^                                  -> a to-do in that week's list
Each is added once per page: saving the page again (or after you've ticked or deleted
the to-do) never adds it twice. No SQL here: the store keeps the pages and to-dos.
"""

import re

from venato import store

DAILY = re.compile(r'["“”]([^"“”\n]{1,120}?)["“”]')
WEEKLY = re.compile(r"\^([^\^\n]{1,120}?)\^")


def _clean(title):
    title = " ".join(title.split()).strip(" .,;:!?-")
    return title[:1].upper() + title[1:] if title else ""


def extract(text):
    """[(period, title)] marked in a page's text, in order, without repeats."""
    found, seen = [], set()
    for period, pattern in (("daily", DAILY), ("weekly", WEEKLY)):
        for m in pattern.finditer(text or ""):
            title = _clean(m.group(1))
            if title and (period, title.lower()) not in seen:
                seen.add((period, title.lower()))
                found.append((period, title))
    return found


def save(day, text, make_todos=True):
    """
    Save a page; with make_todos, add the to-dos marked in it (only ones not added before).
    Returns the to-dos added, as (period, title).
    """
    store.save_journal(day, text)
    if not make_todos:
        return []
    added = []
    for period, title in extract(text):
        if not store.journal_todo_new(day, period, title):
            continue
        start = store.start_of_period(period, store._as_date(day))
        if any(t["title"].lower() == title.lower() for t in store.todos_for(period, start)):
            continue                              # already on that list
        store.add_todo(title, period, start, repeat=False)   # one-offs, even weekly ones
        added.append((period, title))
    return added
