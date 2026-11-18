"""
What every tool shares: the Result / Pending / ToolError types, and input helpers (dates,
periods, finding an item by a loosely typed title).
"""

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Callable

from venato import store


class ToolError(Exception):
    """A problem Claude should explain to the user (bad input, unknown name...)."""


@dataclass
class Pending:
    summary: str                   # what will happen, shown next to Confirm / Cancel
    run: Callable[[], "Result"]    # does it


@dataclass
class Result:
    text: str                      # what Claude is told
    changed: bool = False          # data changed (the page should refresh)
    pending: Pending | None = field(default=None)


def _day(value):
    """Validate an ISO date string; returns it normalised."""
    try:
        return date.fromisoformat(str(value).strip()).isoformat()
    except ValueError:
        raise ToolError(f"'{value}' isn't a date. Use YYYY-MM-DD.")


def nice_day(iso):
    """'2026-10-29' -> 'Thu 29 Oct'."""
    d = date.fromisoformat(iso)
    return f"{d:%a} {d.day} {d:%b}"


def _date_range(start_date, end_date, max_days=93):
    first, last = _day(start_date), _day(end_date)
    if last < first:
        first, last = last, first
    if (date.fromisoformat(last) - date.fromisoformat(first)).days >= max_days:
        raise ToolError(f"That range is too long; ask for at most {max_days} days at a time.")
    return first, last


def _now():
    """Now in the user's time zone, without a timezone attached (tests replace this)."""
    return store.local_now()


PERIOD_NAMES = {"daily": "day", "weekly": "week", "monthly": "month", "yearly": "year"}


def _period(value, allowed=store.TODO_PERIODS):
    v = str(value).strip().lower()
    v = {"day": "daily", "today": "daily", "week": "weekly", "month": "monthly", "year": "yearly"}.get(v, v)
    if v not in allowed:
        raise ToolError("period must be " + " or ".join(f"'{a}'" for a in allowed) + ".")
    return v


def _period_day(value):
    return date.fromisoformat(_day(value)) if value else store.local_today()


FILLER_WORDS = {"the", "a", "an", "my", "to", "do", "finish", "finished", "done", "complete", "tick", "off",
                "goal", "todo"}


def _words(text):
    return set(re.findall(r"[a-z0-9]+", text.lower())) - FILLER_WORDS


def _best_match(pool, text):
    """Items by exact title, then part of a title, then the most shared words
    ("finish problem sheet" -> "Problem sheet 4")."""
    want = str(text).strip().lower()
    exact = [x for x in pool if x["title"].lower() == want]
    part = [x for x in pool if want in x["title"].lower()]
    words = _words(want)
    scores = {x["id"]: len(words & _words(x["title"])) for x in pool}
    best = max(scores.values(), default=0)
    return exact or part or [x for x in pool if best and scores[x["id"]] == best]
