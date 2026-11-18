"""
Tools for deadlines: add, list, complete, edit and delete, found by a loosely typed title.
"""

from venato import store

from .common import Pending, Result, ToolError, _best_match, _day, nice_day


def describe_deadline(d, today=None):
    return f"'{d['title']}' due {nice_day(d['due'])} ({store.countdown(d['due'], today)})"


def _find_deadline(deadline, include_done=False):
    found = store.get_deadline(str(deadline).strip())
    if found:
        return found
    matches = _best_match(store.deadlines(include_done), deadline)
    if len(matches) == 1:
        return matches[0]
    if matches:
        options = "; ".join(f"id {d['id']}: {describe_deadline(d)}" for d in matches)
        raise ToolError(f"More than one deadline matches '{deadline}': {options}. Ask the user which one, or pass its id.")
    raise ToolError(f"There's no deadline matching '{deadline}'. Use list_deadlines to see them.")


def add_deadline(title, due, notes=None):
    try:
        did = store.add_deadline(title, _day(due), notes)
    except ValueError as e:
        raise ToolError(str(e))
    return Result(f"Added deadline {describe_deadline(store.get_deadline(did))}.", changed=True)


def list_deadlines(include_done=False):
    rows = store.deadlines(bool(include_done))
    if not rows:
        return Result("No deadlines.")
    return Result("\n".join(f"- id {d['id']}: {describe_deadline(d)}" + (" [done]" if d["done"] else "")
                            + (f" — {d['notes']}" if d["notes"] else "") for d in rows))


def complete_deadline(deadline, done=True):
    d = _find_deadline(deadline, include_done=True)
    store.set_deadline_done(d["id"], bool(done))
    return Result(f"{'Ticked off' if done else 'Reopened'} {describe_deadline(d)}.", changed=True)


def edit_deadline(deadline, title=None, due=None, notes=None):
    d = _find_deadline(deadline, include_done=True)
    try:
        store.update_deadline(d["id"], title=title if title is not None else store.KEEP,
                              due=_day(due) if due else store.KEEP, notes=notes if notes is not None else store.KEEP)
    except ValueError as e:
        raise ToolError(str(e))
    return Result(f"Updated: {describe_deadline(store.get_deadline(d['id']))}.", changed=True)


def delete_deadline(deadline, confirmed=False):
    d = _find_deadline(deadline, include_done=True)
    if not confirmed:
        return Result("", pending=Pending(f"Delete the deadline {describe_deadline(d)}",
                                          lambda: delete_deadline(d["id"], True)))
    store.delete_deadline(d["id"])
    return Result(f"Deleted the deadline '{d['title']}'.", changed=True)
