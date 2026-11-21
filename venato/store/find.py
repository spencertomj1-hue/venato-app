"""
Search: one box for everything (Home). Blocks add their own kinds (venato/blocks).

(The module isn't called search.py so that store.search stays the function.)
"""

from .database import db


# kind -> (SQL giving (id, title, detail, date, extra), the `haystack` that must contain every word, and
# optionally the order: "name" (by title) or "date" (newest first, the default). Blocks add their own kinds.
_SEARCH = {
    "To-do": ("SELECT id, title, notes, period_start, period FROM todos", "title || ' ' || COALESCE(notes, '')"),
    "Goal": ("SELECT id, title, unit, period_start, period FROM (SELECT * FROM goals WHERE closed = 0)", "title"),
    "Deadline": ("SELECT id, title, notes, due, done FROM deadlines", "title || ' ' || COALESCE(notes, '')"),
    "Timetable": ("SELECT id, label, details, date, track || ' ' || start || '-' || \"end\" FROM tt_entries",
                  "label || ' ' || COALESCE(details, '')"),
    "Outlook": ("SELECT uid, title, location, date, start FROM tt_outlook",
                "title || ' ' || COALESCE(location, '') || ' ' || COALESCE(description, '')"),
    "Review": ("SELECT week_start, 'Weekly review', COALESCE(went_well, '') || ' ' || COALESCE(to_change, ''), "
               "week_start, NULL FROM weekly_reviews", "COALESCE(went_well, '') || ' ' || COALESCE(to_change, '')"),
}


_SEARCH_OWNER = {"To-do": "goals", "Goal": "goals", "Deadline": "goals",
                 "Timetable": "timetable", "Outlook": "timetable", "Review": "stats"}


def search(query, per_kind=8):
    """Everything matching all the words in `query` (any case), as
    [{kind, id, title, detail, date, extra}], newest first within each kind."""
    words = str(query or "").split()
    if not words:
        return []
    from venato import blocks
    out = []
    with db() as conn:
        on = set(blocks.chosen_keys())
        built_in = {k: v for k, v in _SEARCH.items() if _SEARCH_OWNER[k] in on}   # only the switched-on blocks' kinds
        for kind, (select, haystack, *order) in {**built_in, **blocks.search_kinds()}.items():
            where = " AND ".join(f"{haystack} LIKE ? ESCAPE '\\'" for _ in words)
            params = ["%" + w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%" for w in words]
            order = " ORDER BY 2" if order == ["name"] else " ORDER BY 4 DESC"
            rows = conn.execute(f"{select} WHERE {where}{order} LIMIT {int(per_kind)}", params).fetchall()
            out += [{"kind": kind, "id": r[0], "title": r[1], "detail": r[2], "date": r[3], "extra": r[4]} for r in rows]
    return out
