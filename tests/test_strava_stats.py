"""Strava (with a fake Strava), the runs and gym-volume charts' data, and the journal's left page."""

import importlib
import time
from datetime import date, datetime, timezone

import pytest
import requests

from tests.conftest import MemoryKeyring


class Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


@pytest.fixture
def strava(store, monkeypatch):
    from venato import strava as module
    module = importlib.reload(module)
    monkeypatch.setattr(module, "keyring", MemoryKeyring())
    module.save_app("123", "secret")
    return module


def tokens(expires_in=21600, n=1):
    return {"access_token": f"access{n}", "refresh_token": f"refresh{n}", "expires_at": int(time.time()) + expires_in}


ACTIVITIES = [
    {"id": 11, "name": "Morning Run", "sport_type": "Run", "start_date": "2026-11-05T07:10:00Z",
     "distance": 5230.4, "moving_time": 1650, "total_elevation_gain": 22.0, "average_heartrate": 151.2},
    {"id": 12, "name": "Commute", "sport_type": "Ride", "start_date": "2026-11-05T17:00:00Z", "distance": 8000.0,
     "moving_time": 1500},
]


def fake_get(calls, pages=None):
    def get(url, params=None, headers=None, timeout=None):
        calls.append((url, headers["Authorization"], params))
        return Resp(200, ACTIVITIES if params["page"] == 1 else [])
    return get


def test_sync_stores_activities_and_ticks_the_run(strava, store, monkeypatch):
    from venato import training
    monkeypatch.setattr(store, "local_today", lambda: date(2026, 11, 4))
    first, race, sessions = training.generate(date(2026, 11, 5))
    store.create_plan(training.PLAN_NAME, first.isoformat(), race.isoformat(), sessions)
    strava._save_tokens(tokens())
    calls = []
    status = strava.sync(force=True, get=fake_get(calls), now=datetime(2026, 11, 5, 20, tzinfo=timezone.utc))
    assert status == {"ok": True, "error": None, "activities": 2, "ticked": 1}
    assert calls[0][1] == "Bearer access1" and calls[0][2]["per_page"] == 100
    run = [s for s in store.plan_sessions(store.active_plan()["id"]) if s["date"] == "2026-11-05"][0]
    assert run["done"] and run["actual_km"] == 5.23 and "Morning Run" in run["notes"]
    # The runs chart: the Strava run once (not again for the session it ticked), no bike ride.
    assert store.runs() == [{"date": "2026-11-05", "label": "Morning Run", "distance_km": 5.23, "source": "Strava"}]
    # A training run ticked by hand, with no Strava run, counts too.
    other = [s for s in store.plan_sessions(store.active_plan()["id"]) if s["date"] == "2026-11-07"][0]
    store.update_session(other["id"], done=True)
    assert [r["source"] for r in store.runs()] == ["Strava", "Training plan"]
    # Unticked by hand later: a new sync doesn't tick it again.
    store.update_session(run["id"], done=False)
    strava.sync(force=True, get=fake_get([]), now=datetime(2026, 11, 5, 21, tzinfo=timezone.utc))
    assert not store.get_session(run["id"])["done"]


def test_expired_token_refreshes_and_keeps_the_new_refresh_token(strava):
    strava._save_tokens(tokens(expires_in=-10))
    posts = []

    def post(url, data=None, timeout=None):
        posts.append(data)
        return Resp(200, tokens(n=2))
    calls = []
    strava.sync(force=True, get=fake_get(calls), post=post)
    assert posts[0]["grant_type"] == "refresh_token" and posts[0]["refresh_token"] == "refresh1"
    assert calls[0][1] == "Bearer access2" and strava._get(strava.KEY_TOKENS)["refresh_token"] == "refresh2"


def test_connect_flow(strava, monkeypatch):
    monkeypatch.setattr(strava.requests, "post", lambda url, data=None, timeout=None: Resp(200, tokens(n=9)))
    url = strava.start_connect(open_browser=False)
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A8766%2Fstrava%2Fcallback" in url and "activity%3Aread_all" in url
    state = url.split("state=")[1].split("&")[0]
    r = requests.get(f"http://127.0.0.1:{strava.PORT}/strava/callback?code=x&state={state}&scope=read", timeout=5)
    assert "permission to see your activities" in r.text and not strava.connected()     # box unticked
    strava.stop_connect()
    url = strava.start_connect(open_browser=False)
    state = url.split("state=")[1].split("&")[0]
    r = requests.get(f"http://127.0.0.1:{strava.PORT}/strava/callback?code=x&state={state}"
                     "&scope=read,activity:read_all", timeout=5)
    assert "connected" in r.text and strava.connected()
    strava.stop_connect()


def test_gym_volume(store):
    store.save_gym_session("2026-11-01", "Push", [{"exercise": "Bench press", "weight_kg": 60, "sets": 3, "reps": 8}])
    store.save_gym_session("2026-11-04", "Push", [{"exercise": "bench press", "weight_kg": 62.5, "sets": 3, "reps": 8},
                                                  {"exercise": "Dips", "sets": 3, "reps": 10}])
    vols = [(r["exercise"].lower(), r["date"], r["volume"]) for r in store.gym_volume()]
    assert ("bench press", "2026-11-01", 1440.0) in vols and ("bench press", "2026-11-04", 1500.0) in vols
    assert ("dips", "2026-11-04", 0.0) in vols                 # bodyweight: no kg


def test_entry_fields_keep_the_journal(store):
    store.save_journal("2026-11-05", "Today was good.")
    store.set_entry_field("2026-11-05", "mood", 4)
    store.set_entry_field("2026-11-05", "sleep", 7.5)
    store.set_entry_field("2026-11-05", "energy", 12)          # clamped to 10
    e = store.get_entry("2026-11-05")
    assert (e["mood"], e["sleep"], e["energy"], e["notes"]) == (4, 7.5, 10, "Today was good.")


def test_stats_page_with_runs_and_gym(store):
    from streamlit.testing.v1 import AppTest
    store.save_gym_session(date.today().isoformat(), "Push",
                           [{"exercise": "Bench press", "weight_kg": 60, "sets": 3, "reps": 8}])
    store.save_strava([{"id": "1", "date": date.today().isoformat(), "start": "07:00", "name": "Run", "sport": "Run",
                        "distance_km": 5.0, "moving_min": 27, "elevation_m": 10, "avg_hr": 150}])

    at = AppTest.from_file(str(__import__("pathlib").Path(__file__).resolve().parents[1] / "app.py"), default_timeout=120)
    at.run()
    at.sidebar.radio[0].set_value("Stats").run()
    assert not at.exception
    headings = [h.value for h in at.subheader]
    assert "Runs" in headings and "Gym: progressive overload" in headings
    assert ("Runs", "1") in [(m.label, m.value) for m in at.metric]


# ---------------------------------------------------------------------------
# Teams meetings from Outlook get their own (yellow) category
# ---------------------------------------------------------------------------

TEAMS_ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:t1
SUMMARY:Project sync
DTSTART:20261105T100000Z
DTEND:20261105T110000Z
DESCRIPTION:Microsoft Teams meeting\nJoin: https://teams.microsoft.com/l/meetup-join/abc
END:VEVENT
BEGIN:VEVENT
UID:t2
SUMMARY:Lecture
LOCATION:Room 2
DTSTART:20261105T130000Z
DTEND:20261105T140000Z
END:VEVENT
END:VCALENDAR
"""


def test_teams_meetings_are_yellow(store):
    from venato import outlook
    rows = outlook.to_rows(outlook.parse(TEAMS_ICS, today=date(2026, 11, 4)))
    assert {r["title"]: r["teams"] for r in rows} == {"Project sync": 1, "Lecture": 0}
    store.replace_outlook(rows)
    cats = {r["id"]: r for r in store.load_categories().to_dict("records")}
    assert cats["teams"]["name"] == "Teams meeting" and cats["teams"]["colour"] == "#FFD60A"
    ev = {e["title"]: e for e in store.outlook_between("2026-11-05", "2026-11-05")}
    assert store.outlook_category("x", ev["Project sync"]["teams"]) == "teams"
    assert store.outlook_category("x", ev["Lecture"]["teams"]) == store.DEFAULT_OUTLOOK_CATEGORY
    # Edited into your own block, it stays yellow.
    block_id = store.detach_outlook(ev["Project sync"]["uid"])
    assert store.get_block(block_id)["category_id"] == "teams"


def test_claude_logs_trackers(store):
    from venato import tools
    tools = importlib.reload(tools)
    with pytest.raises(tools.ToolError):
        tools.log_tracker("Reading", 2, "2026-11-05")                 # no such tracker yet
    tools.add_tracker("Reading", "hours", 0.5)
    assert "2 hours" in tools.log_tracker("reading", 2, "2026-11-05").text
    assert "3.5 hours" in tools.log_tracker("Reading", 1.5, "2026-11-05", add=True).text
    assert "Reading (hours, step 0.5)" in tools.list_trackers().text
    with pytest.raises(tools.ToolError):
        tools.log_tracker("Reading", -10, "2026-11-05", add=True)


def test_stats_shows_trackers(store):
    from streamlit.testing.v1 import AppTest
    t = store.add_day_tracker("Reading", "h", 0.5)
    store.set_day_value(store.local_today().isoformat(), t["id"], 2.5)
    at = AppTest.from_file(str(__import__("pathlib").Path(__file__).resolve().parents[1] / "app.py"), default_timeout=120)
    at.run()
    at.sidebar.radio[0].set_value("Stats").run()
    assert not at.exception
    assert "Trackers" in [h.value for h in at.subheader]
    assert ("Reading (30 days)", "2.5 h") in [(m.label, m.value) for m in at.metric]
