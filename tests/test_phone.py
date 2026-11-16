"""
Talking to Venato from the phone: the PIN, the page, messages going to Claude (stubbed here),
Confirm / Cancel, and the Start Working tools Claude uses for it.
"""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from test_start_working import _setup as setup_bars
from pathlib import Path
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app.py")


@pytest.fixture
def server(store, monkeypatch):
    from venato import assistant, phone, tools
    phone._fails.update(n=0, until=0.0)
    phone._history.clear()
    phone.set_enabled(True, "4321")
    setup_bars(store)
    sent = []

    def fake_turn(text, history=(), key="default"):
        sent.append((text, list(history)))
        if "delete" in text:
            return assistant.Turn(reply="Delete it?", pending=[tools.Pending("Delete 'Gym'", lambda: tools.Result("Deleted."))])
        tools.add_to_session(["Email Sam", "Write the newsletter"])
        return assistant.Turn(reply="Added 2 things to your session list.")

    monkeypatch.setattr(assistant, "run_turn", fake_turn)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), phone.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", sent
    httpd.shutdown()
    httpd.server_close()


def _post(base, path, body=None, pin="4321"):
    req = urllib.request.Request(base + path, json.dumps(body or {}).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Venato-Pin": pin})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_the_page_and_the_pin(server):
    base, _ = server
    with urllib.request.urlopen(base + "/", timeout=10) as r:
        assert r.status == 200 and b"Venato" in r.read()
    assert _post(base, "/api/check", pin="0000")[0] == 401
    assert _post(base, "/api/check") == (200, {"ok": True, "session": []})


def test_too_many_wrong_pins_locks_it(server):
    base, _ = server
    for _ in range(5):
        _post(base, "/api/check", pin="1111")
    code, body = _post(base, "/api/check")                     # even the right PIN, for a while
    assert code == 401 and "Locked" in body["error"]


def test_a_message_goes_to_claude_and_updates_venato(server, store):
    base, sent = server
    code, body = _post(base, "/api/say", {"text": "put email Sam and the newsletter on my start working list"})
    assert code == 200 and body["reply"] == "Added 2 things to your session list."
    assert sent[0][0].startswith("(From my phone) put email Sam")
    assert [i["title"] for i in body["session"]] == ["Email Sam", "Write the newsletter"]
    assert [store.work_bar(i["track"])["name"] for i in store.session_items()] == ["Emails sent", "Newsletter"]
    _post(base, "/api/say", {"text": "and another"})
    assert sent[1][1][:2] == [("user", "put email Sam and the newsletter on my start working list"),
                              ("assistant", "Added 2 things to your session list.")]   # the conversation so far


def test_confirm_and_cancel(server):
    base, _ = server
    body = _post(base, "/api/say", {"text": "delete my gym habit"})[1]
    (pending,) = body["pending"]
    assert pending["summary"] == "Delete 'Gym'"
    assert _post(base, "/api/confirm", {"id": pending["id"], "ok": True})[1]["reply"] == "✓ Deleted."
    assert "already" in _post(base, "/api/confirm", {"id": pending["id"], "ok": True})[1]["reply"]


def test_off_without_a_pin_and_only_on_tailscale(store):
    from venato import phone
    with pytest.raises(ValueError):
        phone.set_enabled(True)                                  # no PIN yet
    with pytest.raises(ValueError):
        phone.set_enabled(True, "12")                            # too short
    assert phone._is_tailnet("100.101.102.103") and not phone._is_tailnet("192.168.1.20")


def test_session_tools(store):
    from venato import tools
    setup_bars(store)
    todo = store.add_detailed_todo("Newsletter", due=store.local_today())
    text = tools.add_to_session(["Email Sam", "Write the newsletter"]).text
    assert "+1 Emails sent" in text and "to-do 'Newsletter'" in text
    assert tools.tick_session_item("newsletter").changed
    assert store.get_todo(todo["id"])["done"] and store.work_state()["weekly"][store.work_bar("Newsletter")["key"]] == 1
    assert "1 of 2 done" in tools.list_session().text
    tools.log_work("Emails sent", 3)
    assert store.work_state()["counts"][store.work_bar("Emails sent")["key"]] == 3
    assert "Emails sent: 3 of 3 at level 1" in tools.list_work_bars().text
    with pytest.raises(tools.ToolError):
        tools.tick_session_item("nothing like this")


def test_settings_phone_tab(store):
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.radio[0].set_value("Settings").run()
    assert not at.exception
    at.text_input(key="phone_pin").set_value("2468").run()
    at.toggle(key="phone_on").set_value(True).run()
    assert not at.exception
    from venato import phone
    assert phone.enabled() and phone.pin() == "2468"
