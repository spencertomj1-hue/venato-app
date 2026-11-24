"""Anonymous usage stats (venato/analytics.py): off by default, nothing typed ever leaves, page timing."""

import json

import pytest


@pytest.fixture
def an(blank_store, monkeypatch):
    from venato import analytics
    monkeypatch.setattr(analytics, "PROJECT_KEY", "phc_test")
    monkeypatch.setattr(analytics, "_start_worker", lambda: None)      # no background thread in tests
    analytics._queue.clear()
    analytics._flags.update(loaded=None, called=set())
    yield analytics
    analytics._queue.clear()
    analytics._flags.update(loaded=None, called=set())


def _events(an):
    return [(e["event"], e["properties"]) for e in an._queue]


def test_off_by_default(an):
    assert not an.opted_in() and not an.enabled()
    an.track("page_viewed", page="Home")
    assert an._queue == []


def test_no_key_means_off_even_when_opted_in(an, monkeypatch):
    monkeypatch.setattr(an, "PROJECT_KEY", "")
    an.set_opted_in(True)
    assert not an.enabled()
    an.track("page_viewed", page="Home")
    assert an._queue == []


def test_key_from_config(an, blank_store, monkeypatch):
    monkeypatch.setattr(an, "PROJECT_KEY", "")
    (blank_store.DATA_DIR / "venato_config.json").write_text(json.dumps({"posthog_key": "phc_cfg"}))
    assert an.project_key() == "phc_cfg"


def test_opted_in_queues_with_anonymous_id(an):
    an.set_opted_in(True)
    an.track("focus_started", kind="focus", minutes=25)
    [e] = an._queue
    assert e["event"] == "focus_started" and e["distinct_id"] == an.install_id()
    p = e["properties"]
    assert p["kind"] == "focus" and p["minutes"] == 25 and p["$process_person_profile"] is False
    assert an.install_id() == an.install_id()                         # made once, then kept


def test_free_text_and_unknown_things_dropped(an):
    an.set_opted_in(True)
    an.track("page_viewed", page="Dear diary, I fancy Sam from Maths!!!", title="secret")
    an.track("made_up_event", page="Home")
    [(name, props)] = _events(an)                                      # the made-up event isn't sent at all
    assert name == "page_viewed" and "page" not in props and "title" not in props


def test_switching_off_clears_the_queue(an):
    an.set_opted_in(True)
    an.track("todo_done")
    an.set_opted_in(False)
    assert an._queue == []


def test_page_timing(an):
    an.set_opted_in(True)
    state = {}
    an.page_changed(state, "Home", now=1000)
    an.page_changed(state, "Home", now=1005)                          # a rerun on the same page: nothing
    an.page_changed(state, "Timetable", now=1065)
    an.page_changed(state, "Home", now=1065 + 10 * 3600)              # left open overnight: capped
    assert [(e, p.get("page"), p.get("seconds")) for e, p in _events(an)] == [
        ("session_started", None, None), ("page_viewed", "Home", None),
        ("page_left", "Home", 65), ("page_viewed", "Timetable", None),
        ("page_left", "Timetable", an.PAGE_CAP), ("page_viewed", "Home", None)]


def test_flush_posts_one_batch_and_survives_offline(an):
    an.set_opted_in(True)
    an.track("todo_done")
    an.track("assistant_used")
    sent = []

    class Ok:
        def raise_for_status(self):
            pass

    assert an.flush(post=lambda url, json, timeout: sent.append((url, json)) or Ok()) == 2
    url, body = sent[0]
    assert url == "https://eu.i.posthog.com/batch/" and body["api_key"] == "phc_test" and len(body["batch"]) == 2
    an.track("todo_done")

    def offline(*a, **k):
        raise OSError("no network")
    assert an.flush(post=offline) == 0 and an._queue == []           # dropped, not retried forever


def test_features_send_events(an, blank_store):
    an.set_opted_in(True)
    from venato.blocks import focus
    from venato import blocks
    focus.start("Essay", minutes=50)
    blank_store.add_life_goal("Run a marathon", months=6)
    blocks.save(["timetable", "focus"])
    names = [e for e, _ in _events(an)]
    assert names == ["focus_started", "life_goal_created", "blocks_changed"]
    assert all("Essay" not in json.dumps(p) and "marathon" not in json.dumps(p) for _, p in _events(an))


class _Resp:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


def test_variant_is_control_when_off(an):
    assert an.variant("onboarding-v2") == "control" and not an.is_on("new-home")


def test_variant_from_posthog_and_exposure_once(an, monkeypatch):
    an.set_opted_in(True)
    asked = []
    monkeypatch.setattr(an.requests, "post", lambda url, json, timeout: asked.append(url) or _Resp(
        {"flags": {"onboarding-v2": {"enabled": True, "variant": "test"}, "new-home": {"enabled": True}}}))
    assert an.variant("onboarding-v2") == "test" and an.variant("onboarding-v2") == "test"
    assert an.is_on("new-home") and an.variant("missing") == "control"
    assert asked == ["https://eu.i.posthog.com/flags/?v=2"]              # fetched once, then kept
    called = [p for e, p in _events(an) if e == "$feature_flag_called"]
    assert [c["$feature_flag"] for c in called] == ["onboarding-v2", "new-home"]
    an.track("todo_done")
    assert _events(an)[-1][1]["$feature/onboarding-v2"] == "test"        # later events can be split by variant


def test_flags_offline_fall_back_to_control(an, monkeypatch):
    an.set_opted_in(True)

    def offline(*a, **k):
        raise OSError("no network")
    monkeypatch.setattr(an.requests, "post", offline)
    assert an.variant("onboarding-v2") == "control"


def test_older_decide_answer_parsed(an):
    assert an._parse_flags({"featureFlags": {"a": "test", "b": True, "c": 3}}) == {"a": "test", "b": True}
