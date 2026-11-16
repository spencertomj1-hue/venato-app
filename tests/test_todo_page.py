"""
The To-dos page: to-dos with a due day, the user's own to-do category and a length, sorted by
urgency, and never on the timetable; and the category filters on Home's to-do cards.
"""

from datetime import datetime, timedelta
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def test_detailed_todos_sort_by_due_day(store):
    today = store.local_today()
    later = store.add_detailed_todo("Later", due=today + timedelta(days=10))
    soon = store.add_detailed_todo("Soon", due=today, minutes=90)
    late = store.add_detailed_todo("Late", due=today - timedelta(days=2))
    assert [t["title"] for t in store.all_open_todos(today)] == ["Late", "Soon", "Later"]
    soon = store.get_todo(soon["id"])
    assert (soon["minutes"], soon["in_diary"], soon["period"]) == (90, True, "daily")
    assert store.get_todo(later["id"])["period"] == "weekly"
    assert store.todo_due(store.get_todo(late["id"])) == today - timedelta(days=2)


def test_old_todos_are_due_at_the_end_of_their_list(store):
    today = store.local_today()
    weekly = store.add_todo("Weekly", "weekly", today)
    assert store.todo_due(weekly) == store.end_of_period("weekly", store.start_of_period("weekly", today))
    assert store.todo_due(store.add_todo("Daily", "daily", today)) == today


def test_todo_categories_are_the_users_own(store):
    repairs = store.add_todo_group("At home repairs")
    assert store.add_todo_group("at home repairs")["id"] == repairs["id"]       # same name, same category
    t = store.add_detailed_todo("Fix tap", group_id=repairs["id"])
    assert store.get_todo(t["id"])["group_id"] == repairs["id"]
    store.update_todo_group(repairs["id"], name="Repairs", colour="#123456")
    assert store.todo_groups() == [{"id": repairs["id"], "name": "Repairs", "colour": "#123456"}]
    store.delete_todo_group(repairs["id"])
    assert store.todo_groups() == []
    assert store.get_todo(t["id"])["group_id"] is None                            # the to-do stays


def test_todos_stay_off_the_timetable(store):
    from venato import autoplan
    today = store.local_today()
    now = datetime.combine(today, datetime.min.time()).replace(hour=9)
    t = store.add_detailed_todo("Essay", due=today, minutes=90)
    autoplan.schedule_todos(today=today, now=now)              # as it used to: a block for the to-do
    store.put_block({"id": f"{store.TODO_PAST}{t['id']}:{today}:08:00", "date": today.isoformat(), "track": "plan",
                     "start": "08:00", "end": "08:30", "label": "Essay", "category_id": None})
    store.put_block({"id": "mine", "date": today.isoformat(), "track": "plan", "start": "11:00", "end": "12:00",
                     "label": "My own block", "category_id": None})
    autoplan.run(now=now)                                      # now every to-do block is cleared, and none come back
    assert store.get_block(store.TODO_BLOCK + t["id"]) is None
    with store.db() as conn:
        assert [b["id"] for b in store.blocks_for(conn, today.isoformat(), "plan")] == ["mine"]
    autoplan.run(now=now)
    assert store.get_block(store.TODO_BLOCK + t["id"]) is None


def test_changing_the_due_day_moves_it_between_lists(store):
    today = store.local_today()
    t = store.add_detailed_todo("Call", due=today)
    store.update_todo(t["id"], due=today + timedelta(days=5))
    assert store.get_todo(t["id"])["period"] == "weekly"
    store.update_todo(t["id"], due=today)
    assert store.get_todo(t["id"])["period"] == "daily"


def test_home_filters_and_todos_page(store):
    repairs = store.add_todo_group("At home repairs")
    store.add_detailed_todo("Fix tap", group_id=repairs["id"])
    store.add_detailed_todo("Email Sam")
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    assert at.button(key="home_td_all").label == "See all"
    at.pills(key="home_td_filter").set_value(repairs["id"]).run()
    assert not at.exception

    at.button(key="home_td_all").click().run()
    assert not at.exception
    assert at.header[0].value == "To-dos"
    at.pills(key="td_filter").set_value(repairs["id"]).run()
    assert not at.exception
    assert [c.label for c in at.checkbox if c.key and c.key.startswith("td_")] == ["Fix tap"]

    # The pop-up opens (AppTest reruns the whole page, so it can't keep a dialog open to fill it in).
    at.button(key="td_new").click().run()
    assert not at.exception
    assert at.text_input(key="tdn_title").label == "What needs doing?"
    assert at.selectbox(key="tdn_group").options == ["No category", "At home repairs", "+ New category…"]
