"""
Weekly reviews: what went well and what to change, one per week (by its first day).
"""

from .database import KEEP, db
from .dates import _as_date, stamp


_REVIEW_COLS = ("week_start", "seen_at", "went_well", "to_change", "kept")


def get_review(week_start):
    """The saved review row for a week ({} if none)."""
    with db() as conn:
        row = conn.execute(f"SELECT {', '.join(_REVIEW_COLS)} FROM weekly_reviews WHERE week_start = ?",
                           (_as_date(week_start).isoformat(),)).fetchone()
    return dict(zip(_REVIEW_COLS, row)) if row else {}


def save_review(week_start, went_well=KEEP, to_change=KEEP, kept=KEEP, seen=False):
    """Create or update a week's review: mark it seen and/or save the reflections.
    kept: did they do what they said they'd change the week before ('yes' / 'partly' / 'no' / None)."""
    week = _as_date(week_start).isoformat()
    with db() as conn:
        conn.execute("INSERT OR IGNORE INTO weekly_reviews (week_start) VALUES (?)", (week,))
        if seen:
            conn.execute("UPDATE weekly_reviews SET seen_at = COALESCE(seen_at, ?) WHERE week_start = ?", (stamp(), week))
        for col, value in (("went_well", went_well), ("to_change", to_change), ("kept", kept)):
            if value is not KEEP:
                conn.execute(f"UPDATE weekly_reviews SET {col} = ? WHERE week_start = ?",
                             ((value or "").strip() or None, week))


def reviews():
    """Weeks that have a review, newest first: [{week_start, seen_at, went_well, to_change, kept}]."""
    with db() as conn:
        rows = conn.execute(f"SELECT {', '.join(_REVIEW_COLS)} FROM weekly_reviews "
                            "ORDER BY week_start DESC").fetchall()
    return [dict(zip(_REVIEW_COLS, r)) for r in rows]
