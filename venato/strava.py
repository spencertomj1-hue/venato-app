"""
Strava: the user's runs (and other activities), read only.

Connecting (Settings → Strava):
  1. The user makes a free API app at strava.com/settings/api with "Authorization Callback
     Domain" = localhost, and pastes its Client ID and Client Secret into Venato (kept in the
     system's secret store, never in a file).
  2. "Connect" starts a tiny one-off web server on 127.0.0.1 to catch Strava's redirect and
     opens Strava's "Authorize" page. The code is swapped for tokens (also in the secret store).

Syncing (on app load, at most every 30 minutes, or "Sync now"): activities since the last sync
(the last 60 days the first time) go into strava_activities (store.py). A run ticks off that
day's training run if it isn't done yet, with the distance Strava measured.

Strava API v3: tokens last 6 hours and are refreshed with the refresh token (which may change,
so the new one is always saved). Tokens and the secret are never logged or shown.
"""

import json
import secrets
import threading
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import keyring
import requests

from venato import store

AUTH_URL = "https://www.strava.com/oauth/authorize"
TOKEN_URL = "https://www.strava.com/oauth/token"
API = "https://www.strava.com/api/v3"
SCOPES = "read,activity:read_all"
PORT = 8766
REDIRECT_URI = f"http://localhost:{PORT}/strava/callback"

KEY_SERVICE = "Venato"
KEY_APP, KEY_TOKENS = "strava-app", "strava-tokens"
TIMEOUT = 15
SYNC_EVERY = timedelta(minutes=30)
FIRST_SYNC_DAYS = 60
RUN_TYPES = ("Run", "TrailRun", "VirtualRun")

_lock = threading.Lock()


class StravaError(Exception):
    """A problem to show the user (never contains tokens or the secret)."""


# ---------------------------------------------------------------------------
# Secrets (system secret store)
# ---------------------------------------------------------------------------

def _get(account):
    try:
        raw = keyring.get_password(KEY_SERVICE, account)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def _put(account, value):
    keyring.set_password(KEY_SERVICE, account, json.dumps(value))


def app_credentials():
    return _get(KEY_APP)


def save_app(client_id, client_secret):
    client_id, client_secret = (client_id or "").strip(), (client_secret or "").strip()
    if not client_id or not client_secret:
        raise StravaError("Paste both the Client ID and the Client Secret.")
    _put(KEY_APP, {"client_id": client_id, "client_secret": client_secret})


def connected():
    return bool(_get(KEY_TOKENS))


def disconnect():
    """Revoke access (best effort), forget the tokens, and remove the imported activities."""
    tokens = _get(KEY_TOKENS)
    if tokens:
        try:
            requests.post("https://www.strava.com/oauth/deauthorize",
                          data={"access_token": tokens["access_token"]}, timeout=TIMEOUT)
        except requests.RequestException:
            pass
    try:
        keyring.delete_password(KEY_SERVICE, KEY_TOKENS)
    except Exception:
        pass
    store.clear_strava()
    store.save_settings(strava_synced=None)


# ---------------------------------------------------------------------------
# Signing in
# ---------------------------------------------------------------------------

def _save_tokens(data):
    _put(KEY_TOKENS, {"access_token": data["access_token"], "refresh_token": data["refresh_token"],
                      "expires_at": int(data["expires_at"]) - 60})


def _token_request(payload, post=None):
    app = app_credentials()
    if not app:
        raise StravaError("Add your Strava app's Client ID and Secret first.")
    try:
        r = (post or requests.post)(TOKEN_URL, data={**payload, "client_id": app["client_id"],
                                                     "client_secret": app["client_secret"]}, timeout=TIMEOUT)
    except requests.RequestException:
        raise StravaError("Couldn't reach Strava. Check your internet connection.") from None
    if r.status_code != 200:
        raise StravaError(f"Strava refused the sign-in (HTTP {r.status_code}). Check the Client ID and Secret, "
                          "and that the app's Authorization Callback Domain is localhost.")
    return r.json()


def auth_url(state):
    app = app_credentials()
    return AUTH_URL + "?" + urlencode({"client_id": app["client_id"], "redirect_uri": REDIRECT_URI,
                                       "response_type": "code", "approval_prompt": "auto", "scope": SCOPES,
                                       "state": state})


class _Catcher(BaseHTTPRequestHandler):
    def log_message(self, *args):                 # no logging (the URL holds the one-time code)
        pass

    def do_GET(self):
        url = urlparse(self.path)
        if url.path != "/strava/callback":
            self.send_response(404)
            self.end_headers()
            return
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        ok, message = False, "Something went wrong."
        if q.get("state") != self.server.state:
            message = "That sign-in didn't come from Venato (the state didn't match). Try Connect again."
        elif "error" in q:
            message = "Strava access wasn't allowed."
        elif "activity:read" not in q.get("scope", ""):
            message = "Venato needs permission to see your activities. Connect again and leave that box ticked."
        elif "code" in q:
            try:
                _save_tokens(_token_request({"grant_type": "authorization_code", "code": q["code"]}))
                ok, message = True, "Strava is connected. You can close this tab and go back to Venato."
            except StravaError as e:
                message = str(e)
        self.server.result = (ok, message)
        body = (f"<html><body style='font-family:sans-serif;padding:40px'><h2>{'✓' if ok else '✗'} "
                f"{message}</h2></body></html>").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)
        threading.Thread(target=self.server.shutdown, daemon=True).start()


_server = {"server": None}


def start_connect(open_browser=True):
    """Start catching Strava's redirect (up to 5 minutes) and return the Authorize URL."""
    stop_connect()
    state = secrets.token_hex(8)
    try:
        server = HTTPServer(("127.0.0.1", PORT), _Catcher)
    except OSError:
        raise StravaError(f"Port {PORT} is busy on this computer. Close whatever uses it and try again.") from None
    server.state, server.result = state, None
    threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Timer(300, server.shutdown).start()
    _server["server"] = server
    url = auth_url(state)
    if open_browser:
        webbrowser.open(url)
    return url


def connect_result():
    server = _server["server"]
    return server.result if server else None


def stop_connect():
    server = _server["server"]
    if server:
        threading.Thread(target=server.shutdown, daemon=True).start()
        server.server_close()
        _server["server"] = None


# ---------------------------------------------------------------------------
# Calling the API
# ---------------------------------------------------------------------------

def _access_token(post=None):
    with _lock:
        tokens = _get(KEY_TOKENS)
        if not tokens:
            raise StravaError("Strava isn't connected.")
        if tokens["expires_at"] > time.time():
            return tokens["access_token"]
        try:
            _save_tokens(_token_request({"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"]}, post))
        except StravaError:
            raise StravaError("Strava's sign-in expired. Connect again in Settings → Strava.") from None
        return _get(KEY_TOKENS)["access_token"]


def activities_since(after, get=None, post=None):
    """Every activity that started after `after` (a UTC datetime), oldest pages first."""
    token = _access_token(post)
    out = []
    for page in range(1, 30):
        try:
            r = (get or requests.get)(f"{API}/athlete/activities", timeout=TIMEOUT,
                                      headers={"Authorization": f"Bearer {token}"},
                                      params={"after": int(after.timestamp()), "per_page": 100, "page": page})
        except requests.RequestException:
            raise StravaError("Couldn't reach Strava. Check your internet connection.") from None
        if r.status_code == 401:
            raise StravaError("Strava's sign-in expired. Connect again in Settings → Strava.")
        if r.status_code == 429:
            raise StravaError("Strava says to slow down (rate limit). Try again in 15 minutes.")
        if r.status_code != 200:
            raise StravaError(f"Strava answered with an error (HTTP {r.status_code}).")
        batch = r.json()
        out += batch
        if len(batch) < 100:
            break
    return out


def to_rows(activities):
    rows = []
    for a in activities:
        start = datetime.fromisoformat(a["start_date"].replace("Z", "+00:00")).astimezone(store.tz())
        rows.append({
            "id": str(a["id"]), "date": start.date().isoformat(), "start": start.strftime("%H:%M"),
            "name": a.get("name") or "", "sport": a.get("sport_type") or a.get("type") or "",
            "distance_km": round((a.get("distance") or 0) / 1000, 2),
            "moving_min": round((a.get("moving_time") or 0) / 60, 1),
            "elevation_m": a.get("total_elevation_gain"), "avg_hr": a.get("average_heartrate"),
        })
    return rows


def is_run(row):
    return row["sport"] in RUN_TYPES


def _match_training(rows):
    """A Strava run ticks off that day's (not yet done) training run. Returns how many."""
    plan = store.active_plan()
    if not plan:
        return 0
    sessions = store.plan_sessions(plan["id"])
    ticked = 0
    for a in rows:
        if not is_run(a) or store.strava_matched(a["id"]):
            continue
        for s in sessions:
            if s["date"] == a["date"] and not s["done"] and s["kind"] != "strength":
                store.update_session(s["id"], done=True, actual_km=a["distance_km"],
                                     notes=s["notes"] or f"From Strava: {a['name']}")
                store.strava_matched(a["id"], s["id"])
                s["done"] = True
                ticked += 1
                break
    return ticked


def sync(force=False, get=None, post=None, now=None):
    """Pull new activities. Returns {ok, error, activities, ticked}, or None if not connected / not time yet."""
    if not connected():
        return None
    now = now or datetime.now(timezone.utc)
    last = store.load_settings().get("strava_synced")
    if not force and last and now - datetime.fromisoformat(last) < SYNC_EVERY:
        return None
    after = datetime.fromisoformat(last) - timedelta(days=2) if last else now - timedelta(days=FIRST_SYNC_DAYS)
    try:
        rows = to_rows(activities_since(after, get, post))
    except StravaError as e:
        return {"ok": False, "error": str(e)}
    store.save_strava(rows)
    ticked = _match_training(rows)
    store.save_settings(strava_synced=now.isoformat())
    return {"ok": True, "error": None, "activities": len(rows), "ticked": ticked}


def last_synced():
    last = store.load_settings().get("strava_synced")
    return datetime.fromisoformat(last).astimezone(store.tz()).replace(tzinfo=None) if last else None
