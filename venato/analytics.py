"""
Anonymous usage stats, opt-in (Settings -> About, or setup's Welcome step). Off unless the user turns it on.

What is sent: an event name ("page_viewed", "focus_started", ...), a random install id made on this computer,
the app version and the operating system, and a few properties from a fixed list: page names, block keys,
setup step names, counts and durations. Never anything the user typed (journal, goals, to-dos, chat), never
names, emails or calendar links: track() drops any property that isn't on the list below, and any text
value that isn't a short plain word.

Where it goes: PostHog (EU), as anonymous events (no person profiles). The project key is PROJECT_KEY, or
"posthog_key" in venato_config.json; with no key nothing is sent even when switched on.

Events are queued and sent in the background in batches; offline, they're dropped. Nothing here can raise
into the app. No Streamlit here.

Feature flags / A/B tests: variant("flag-key") gives this install's variant of a PostHog flag ("control" when
switched off, offline or unknown). Flags are fetched once a day (the first time blocking for up to FLAG_TIMEOUT
seconds, so a new install's setup is already in its group) and kept in settings.json, so a variant doesn't change
mid-session. The first time a flag is used in a session, "$feature_flag_called" is sent (PostHog's exposure event
for experiments), and every later event carries "$feature/<key>" so results can be split by variant.
"""

import atexit
import json
import platform
import re
import threading
import time
import uuid
from datetime import datetime, timezone

import requests

from venato import store

PROJECT_KEY = ""                                  # PostHog project API key (write-only, safe to ship). Empty: off.
HOST = "https://eu.i.posthog.com"                 # EU cloud; "posthog_host" in venato_config.json overrides
SEND_EVERY = 30                                   # seconds between batches
MAX_QUEUE = 500                                   # beyond this, new events are dropped (offline for a long time)
TIMEOUT = 5
PAGE_CAP = 30 * 60                                # a page left open overnight counts as 30 minutes, not 9 hours
FLAGS_EVERY = 24 * 60 * 60                        # seconds between fetching flags
FLAG_TIMEOUT = 2                                  # a new install waits at most this long for its flags
CONTROL = "control"

# Every event the app may send, and the properties each may carry. Anything else is dropped.
EVENTS = {
    "session_started": set(),
    "page_viewed": {"page"},
    "page_left": {"page", "seconds"},
    "onboarding_step": {"step", "index"},
    "onboarding_finished": {"skipped"},
    "focus_started": {"kind", "minutes"},
    "life_goal_created": {"months"},
    "todo_done": set(),
    "assistant_used": set(),
    "blocks_changed": {"count", "blocks"},
    "$feature_flag_called": {"$feature_flag", "$feature_flag_response"},
}
_WORD = re.compile(r"^[A-Za-z0-9 _\-.,]{1,80}$")   # page names, block keys, step names: never free text

_queue, _lock = [], threading.Lock()
_worker = [None]
_flags = {"loaded": None, "called": set()}     # this session's flags, and the ones already reported


# ---------------------------------------------------------------------------
# Switch and identity
# ---------------------------------------------------------------------------

def _config():
    try:
        return json.loads((store.DATA_DIR / "venato_config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def project_key():
    key = _config().get("posthog_key") or PROJECT_KEY
    return key.strip() if isinstance(key, str) else ""


def host():
    h = _config().get("posthog_host")
    return (h if isinstance(h, str) and h.startswith("https://") else HOST).rstrip("/")


def opted_in():
    return bool(store.load_settings().get("analytics", False))


def enabled():
    """Switched on by the user, and there's somewhere to send it."""
    return opted_in() and bool(project_key())


def set_opted_in(on):
    store.save_settings(analytics=bool(on))
    if not on:
        with _lock:
            _queue.clear()                        # switched off: what's waiting isn't sent either
    _flags["loaded"], _flags["called"] = None, set()


def install_id():
    """A random id for this install, made the first time it's needed. Not tied to the person or the computer."""
    s = store.load_settings()
    if not s.get("install_id"):
        s = store.save_settings(install_id=str(uuid.uuid4()))
    return s["install_id"]


# ---------------------------------------------------------------------------
# Tracking
# ---------------------------------------------------------------------------

def clean(event, props):
    """Only the allowed properties of an allowed event, as numbers, booleans or short plain words.
    Returns None for an unknown event."""
    allowed = EVENTS.get(event)
    if allowed is None:
        return None
    out = {}
    for k, v in (props or {}).items():
        if (k not in allowed and not k.startswith("$feature/")) or v is None:
            continue
        if isinstance(v, bool) or (isinstance(v, (int, float)) and not isinstance(v, bool)):
            out[k] = v
        elif isinstance(v, str) and _WORD.match(v):
            out[k] = v
        elif isinstance(v, (list, tuple)) and all(isinstance(x, str) and _WORD.match(x) for x in v):
            out[k] = list(v)[:30]
    return out


def track(event, **props):
    """Queue one event (nothing when switched off). Never raises."""
    try:
        if not enabled():
            return
        cleaned = clean(event, props)
        if cleaned is None:
            return
        from venato import updates
        cleaned.update(clean(event, {f"$feature/{k}": v for k, v in _session_flags().items()}) or {})
        cleaned.update({"app_version": updates.current_version(), "os": platform.system(),
                        "$process_person_profile": False, "$lib": "venato"})
        item = {"event": event, "distinct_id": install_id(), "properties": cleaned,
                "timestamp": datetime.now(timezone.utc).isoformat()}
        with _lock:
            if len(_queue) < MAX_QUEUE:
                _queue.append(item)
        _start_worker()
    except Exception:
        pass


def flush(post=None):
    """Send what's queued in one batch. Returns how many were sent (0 when offline: they're dropped)."""
    with _lock:
        batch, _queue[:] = list(_queue), []
    if not batch or not enabled():
        return 0
    try:
        r = (post or requests.post)(f"{host()}/batch/", json={"api_key": project_key(), "batch": batch}, timeout=TIMEOUT)
        r.raise_for_status()
        return len(batch)
    except Exception:
        return 0


def _loop():
    while True:
        time.sleep(SEND_EVERY)
        flush()


def _start_worker():
    if _worker[0] is None:
        _worker[0] = threading.Thread(target=_loop, name="venato-analytics", daemon=True)
        _worker[0].start()
        atexit.register(flush)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

def page_changed(state, page, now=None):
    """Call on every run with the page being drawn. state: a dict that lasts the session (st.session_state).
    On a new session: session_started. On a new page: page_left for the last one (with its seconds, capped)
    and page_viewed for this one. Reruns on the same page send nothing."""
    now = time.time() if now is None else now
    last, since = state.get("an_page"), state.get("an_since")
    if last == page:
        return
    if last is None:
        track("session_started")
    else:
        track("page_left", page=last, seconds=round(min(max(now - (since or now), 0), PAGE_CAP)))
    track("page_viewed", page=page)
    state["an_page"], state["an_since"] = page, now


# ---------------------------------------------------------------------------
# Feature flags and A/B tests
# ---------------------------------------------------------------------------

def _parse_flags(data):
    """{flag key: variant or True/False} from PostHog's /flags (v2: {"flags": {k: {"enabled", "variant"}}})
    or the older /decide ({"featureFlags": {k: value}}) answer."""
    if isinstance(data.get("flags"), dict):
        return {k: (f.get("variant") or bool(f.get("enabled"))) for k, f in data["flags"].items() if isinstance(f, dict)}
    return {k: v for k, v in (data.get("featureFlags") or {}).items() if isinstance(v, (str, bool))}


def fetch_flags(post=None, now=None):
    """Ask PostHog for this install's flags and keep them in settings.json. Returns them, or None offline."""
    if not enabled():
        return None
    try:
        r = (post or requests.post)(f"{host()}/flags/?v=2", json={"api_key": project_key(), "distinct_id": install_id()},
                 timeout=FLAG_TIMEOUT)
        r.raise_for_status()
        flags = _parse_flags(r.json())
    except Exception:
        return None
    store.save_settings(flags=flags, flags_at=now or time.time())
    return flags


def _session_flags():
    """The flags this session uses: settings.json's (fetched again in the background when a day old), or, the
    first time ever, fetched now. Fixed for the rest of the session. Empty when switched off."""
    if not enabled():
        return {}
    if _flags["loaded"] is None:
        s = store.load_settings()
        if "flags" not in s:
            _flags["loaded"] = fetch_flags() or {}
        else:
            _flags["loaded"] = s.get("flags") or {}
            if time.time() - s.get("flags_at", 0) > FLAGS_EVERY:
                threading.Thread(target=fetch_flags, name="venato-flags", daemon=True).start()   # for next time
    return _flags["loaded"]


def variant(key, default=CONTROL):
    """This install's variant of flag `key` ("control", "test", ... or True/False for an on/off flag).
    `default` when switched off, offline or the flag isn't set up. Reports the exposure once per session."""
    try:
        value = _session_flags().get(key)
        if value is None or value is False:
            return default
        if key not in _flags["called"]:
            _flags["called"].add(key)
            track("$feature_flag_called", **{"$feature_flag": key, "$feature_flag_response": value})
        return value
    except Exception:
        return default


def is_on(key):
    """An on/off flag (a gradual rollout): True only when PostHog says so for this install."""
    v = variant(key, default=False)
    return v is True or (isinstance(v, str) and v != CONTROL)
