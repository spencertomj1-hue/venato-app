"""
Timetable blocks placed for a goal (picked in the Timetable's side panel, then painted on the week).
(To-dos have their own link, by slot: timetable.link_todo / todos.schedule_todo.)

The block itself does the planning: a goal counted in hours gets its time from the block's category and
label (goals.goal_hours), with no link needed. The link is what makes a goal counted by hand ("Show 5 people
round") go up one when a sitting is marked done; marking it not done again takes that back.
"""

from .database import db
from .goals import add_goal_progress


def link_block(block_id, kind, ref):
    """Remember that a block was placed for a goal (kind "goal")."""
    if kind != "goal" or not block_id or not ref:
        raise ValueError("A link needs a block and the goal it's for.")
    with db() as conn:
        conn.execute("INSERT OR REPLACE INTO tt_links (block_id, kind, ref) VALUES (?, ?, ?)", (block_id, kind, ref))


def block_link(block_id):
    """(kind, ref) for a block placed for a goal, or None."""
    with db() as conn:
        row = conn.execute("SELECT kind, ref FROM tt_links WHERE block_id = ?", (block_id,)).fetchone()
    return tuple(row) if row else None


def linked_blocks(kind, ref):
    """The ids of the blocks placed for one goal."""
    with db() as conn:
        return [r[0] for r in conn.execute("SELECT block_id FROM tt_links WHERE kind = ? AND ref = ?", (kind, ref))]


def on_block_status(block_id, was, now):
    """A block's done mark changed from `was` to `now` ("done", "missed" or None): pass it on to the goal it
    was placed for. Only a change into or out of done counts, so it never counts twice."""
    if (was == "done") == (now == "done"):
        return
    link = block_link(block_id)
    if not link or link[0] != "goal":
        return
    with db() as conn:
        row = conn.execute("SELECT habit_id, category_id FROM goals WHERE id = ?", (link[1],)).fetchone()
    if row and row[0] is None and row[1] is None:       # counted by hand (hours and habits count themselves)
        add_goal_progress(link[1], 1 if now == "done" else -1)
