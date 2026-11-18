"""
Tools for the journal: write (add to or replace) a day's entry, and read or search entries.
"""

from venato import store

from .common import Pending, Result, ToolError, _day, nice_day


def write_journal(text, date=None, replace=False, confirmed=False):
    """Add a paragraph to a day's notes / journal entry (today by default); replace=True rewrites the whole entry."""
    day = _day(date) if date else store.local_today().isoformat()
    text = str(text or "").strip()
    if not text:
        raise ToolError("Nothing to write.")
    old = store.get_journal(day)
    if not replace or not old:
        store.append_journal(day, text)
        return Result(f"Added to the journal for {nice_day(day)}.", changed=True)
    if not confirmed:
        return Result("", pending=Pending(f"Replace the journal for {nice_day(day)} ({len(old.split())} words)",
                                          lambda: write_journal(text, day, True, True)))
    store.save_journal(day, text)
    return Result(f"Replaced the journal for {nice_day(day)}.", changed=True)


def read_journal(date=None, start_date=None, end_date=None, query=None, limit=10):
    """Journal entries for a day, a date range and/or matching words, newest first."""
    if date:
        start_date = end_date = date
    first = _day(start_date) if start_date else None
    last = _day(end_date) if end_date else None
    rows = store.journal_entries(query, first, last, limit=min(int(limit), 31))
    if not rows:
        return Result("No journal entries found.")
    return Result("\n\n".join(f"## {nice_day(r['date'])} ({r['date']})\n{r['text']}" for r in rows))
