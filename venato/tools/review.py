"""
Tools for the weekly review: its summary of the week, and saving the answers.
"""

from venato import store

from .common import Pending, Result, _day, nice_day


def weekly_review(date=None):
    """The main numbers for the week containing `date` (default: the latest review week)."""
    from venato import review
    first = store.week_start_of(_day(date)) if date else review.due_week()
    return Result(review.as_text(review.summary(first)))


def save_review_answers(went_well=None, to_change=None, date=None, confirmed=False):
    """Write the weekly review's two reflections (what went well / what to change) for a week."""
    from venato import review
    first = store.week_start_of(_day(date)) if date else review.due_week()
    old = next((r for r in store.reviews() if r["week_start"] == first.isoformat()), {})
    overwrite = [k for k, v in (("went_well", went_well), ("to_change", to_change)) if v is not None and old.get(k)]
    label = f"the week of {nice_day(first.isoformat())}"
    if overwrite and not confirmed:
        return Result("", pending=Pending(f"Replace your review answers for {label}",
                                          lambda: save_review_answers(went_well, to_change, first.isoformat(), True)))
    store.save_review(first, went_well=went_well if went_well is not None else store.KEEP,
                      to_change=to_change if to_change is not None else store.KEEP)
    return Result(f"Saved your review for {label}.", changed=True)
