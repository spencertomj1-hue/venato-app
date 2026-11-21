"""
"Send feedback": a link to a Google Form with the version and system already filled in.
Nothing is sent from the app; the link just opens in the browser. The form's address can be
changed with "feedback_url" in venato_config.json. No Streamlit here.
"""

import json
import platform
from urllib.parse import urlencode

from venato import store
from venato import updates

FORM_URL = ("https://docs.google.com/forms/d/e/1FAIpQLSfKtBy2MutZ__Q5Ivkzz5urT0ABhtF8Rgu5yii2O3bQyLTmWQ/viewform")
VERSION_ENTRY = "entry.1914590086"
SYSTEM_ENTRY = "entry.1813165119"
SYSTEMS = {"Darwin": "MacOS", "Windows": "Windows", "Linux": "Linux"}   # the form's option text
CARD_AFTER_DAYS = 14                                                     # the one-time "How's Venato treating you?"


def form_url():
    """The form's address: "feedback_url" in venato_config.json, else the default."""
    try:
        url = json.loads((store.DATA_DIR / "venato_config.json").read_text(encoding="utf-8")).get("feedback_url")
    except (OSError, ValueError, AttributeError):
        url = None
    return url if isinstance(url, str) and url.strip() else FORM_URL


def feedback_url(system=None, version=None):
    """The form with Version and System pre-filled. A system the form doesn't list is left blank."""
    params = {"usp": "pp_url", VERSION_ENTRY: version or updates.current_version()}
    chosen = SYSTEMS.get(system or platform.system())
    if chosen:
        params[SYSTEM_ENTRY] = chosen
    url = form_url()
    return f"{url}{'&' if '?' in url else '?'}{urlencode(params)}"


def card_due(today=None):
    """The one-time card: 14 days after first using Venato, until answered."""
    s = store.load_settings()
    if s.get("feedback_card_done") or not s.get("first_seen"):
        return False
    try:
        first = store._as_date(s["first_seen"])
    except (TypeError, ValueError):
        return False
    return ((today or store.local_today()) - first).days >= CARD_AFTER_DAYS


def card_done():
    store.save_settings(feedback_card_done=True)
