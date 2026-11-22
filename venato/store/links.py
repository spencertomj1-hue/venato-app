"""
Timetable blocks placed for a to-do or a goal (picked in the Timetable's side panel, then painted on the week).

The block itself does the planning: a goal counted in hours gets its time from the block's category and
label (goals.goal_hours), with no link needed. The link is what makes finishing the block count:
marking it done ticks its to-do, or adds one to a goal counted by hand ("Show 5 people round": a sitting is
one). Marking it not done again takes that back.
"""

from .database import db
from .goals import add_goal_progress
from .todos import set_todo_done


def link_block(block_id, kind, ref):
    """Remember that a block was placed for a to-do (kind "todo") or a goal ("goal")."""
    if kind not in ("todo", "goal") or not block_id or not ref:
        raise ValueError("A link needs a block, a kind (todo or goal) and what it's for.")
    with db() as conn:
        conn.execute("INSERT OR REPLACE INTO tt_links (block_id, kind, ref) VALUES (?, ?, ?)", (block_id, kind, ref))


def block_link(block_id):
    """(kind, ref) for a block placed for a to-do or a goal, or None."""
    with db() as conn:
        row = conn.execute("SELECT kind, ref FROM tt_links WHERE block_id = ?", (block_id,)).fetchone()
    return tuple(row) if row else None


def linked_blocks(kind, ref):
    """The ids of the blocks placed for one to-do or goal."""
    with db() as conn:
        return [r[0] for r in conn.execute("SELECT block_id FROM tt_links WHERE kind = ? AND ref = ?", (kind, ref))]


def on_block_status(block_id, was, now):
    """A block's done mark changed from `was` to `now` ("done", "missed" or None): pass it on to what the
    block was placed for. Only a change into or out of done counts, so it never counts twice."""
    if (was == "done") == (now == "done"):
        return
    link = block_link(block_id)
    if not link:
        return
    kind, ref = link
    done = now == "done"
    if kind == "todo":
        set_todo_done(ref, done)
    else:
        with db() as conn:
            row = conn.execute("SELECT habit_id, category_id FROM goals WHERE id = ?", (ref,)).fetchone()
        if row and row[0] is None and row[1] is None:       # counted by hand (hours and habits count themselves)
            add_goal_progress(ref, 1 if done else -1)
