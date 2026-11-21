"""Send feedback: the pre-filled form link, and the one-time card after two weeks."""

import json
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from streamlit.testing.v1 import AppTest


APP = str(Path(__file__).resolve().parents[1] / "app.py")


def _app():
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    return at


def _query(url):
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


def test_url_has_version_and_system(blank_store):
    from venato import feedback
    q = _query(feedback.feedback_url(system="Darwin", version="1.2.3"))
    assert q["entry.1914590086"] == "1.2.3" and q["entry.1813165119"] == "MacOS" and q["usp"] == "pp_url"
    assert _query(feedback.feedback_url(system="Windows", version="1"))["entry.1813165119"] == "Windows"
    assert _query(feedback.feedback_url(system="Linux", version="1"))["entry.1813165119"] == "Linux"
    assert "entry.1813165119" not in _query(feedback.feedback_url(system="Plan9", version="1"))
    assert feedback.feedback_url(system="Linux").startswith(feedback.FORM_URL)


def test_form_address_comes_from_config(blank_store):
    from venato import feedback
    (blank_store.DATA_DIR / "venato_config.json").write_text(json.dumps({"feedback_url": "https://example.test/form"}))
    assert feedback.feedback_url(system="Linux", version="2").startswith("https://example.test/form?usp=pp_url")


def test_card_after_fourteen_days_once(blank_store):
    from venato import feedback
    from venato.ui import goal_time
    today = blank_store.local_today()
    blank_store.save_settings(first_seen=(today - timedelta(days=13)).isoformat())
    assert not feedback.card_due()
    blank_store.save_settings(first_seen=(today - timedelta(days=14)).isoformat(), ai_enabled=True)
    assert feedback.card_due() and goal_time.needs_items()["feedback"]
    at = _app()
    assert any("treating you" in m.value for m in at.markdown)
    at.button(key="needs_fb_no").click().run()                  # dismissed: gone for good
    assert blank_store.load_settings()["feedback_card_done"] is True
    assert not feedback.card_due()
    assert not any("treating you" in m.value for m in _app().markdown)


def test_card_never_before_first_use(blank_store):
    from venato import feedback
    blank_store.save_settings(first_seen=None)
    assert not feedback.card_due()


def test_about_link(blank_store):
    """Send feedback lives in Settings → About (there's no sidebar any more)."""
    from nav_helpers import goto
    at = _app()
    assert not at.exception
    assert not any("Send feedback" in str(e.proto.label) for e in at.get("link_button"))   # not on Home
    goto(at, "Settings")
    assert not at.exception
    assert any("Send feedback" in str(e.proto.label) for e in at.get("link_button"))
