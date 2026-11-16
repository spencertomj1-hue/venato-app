"""
Talk to Venato from your phone.

A small web page (one text box: dictate with the phone keyboard's mic, then Send) served from the
laptop while Venato is open. What's said goes to Claude with Venato's tools (assistant.run_turn),
so "add a to-do…" or "put email Sam on my start working list" changes the data like the chat does;
the reply shows on the phone.

Safety: it's off until switched on in Settings › Phone, it only listens on the laptop's Tailscale
address (a private network between the user's own devices: 100.64.0.0/10), never on Wi-Fi or the
internet, and every request needs the PIN set in Settings. Too many wrong PINs locks it for a while.
No Streamlit here: the server is a thread started from app.py (ensure_running), one per process.
"""

import hmac
import ipaddress
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from venato import store

PORT = 8600
TAILNET = ipaddress.ip_network("100.64.0.0/10")
HISTORY = 12                      # recent phone messages sent along as context
MAX_FAILS, LOCK_SECONDS = 5, 300  # wrong PINs before a lock, and how long it lasts
PAGE = (Path(__file__).parent / "ui" / "components" / "phone.html")

_lock = threading.Lock()
_server = None                    # (ThreadingHTTPServer, address) while running
_history = []                     # (role, text)
_pending = {}                     # id -> tools.Pending waiting for Confirm
_fails = {"n": 0, "until": 0.0}


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def enabled():
    return bool(store.load_settings().get("phone_enabled"))


def pin():
    return str(store.load_settings().get("phone_pin") or "")


def set_enabled(on, new_pin=None):
    changes = {"phone_enabled": bool(on)}
    if new_pin is not None:
        new_pin = str(new_pin).strip()
        if not (new_pin.isdigit() and 4 <= len(new_pin) <= 12):
            raise ValueError("The PIN must be 4 to 12 digits.")
        changes["phone_pin"] = new_pin
    if on and not (changes.get("phone_pin") or pin()):
        raise ValueError("Set a PIN first.")
    store.save_settings(**changes)


# ---------------------------------------------------------------------------
# Finding the Tailscale address
# ---------------------------------------------------------------------------

def _tailscale_cli():
    found = shutil.which("tailscale")
    if found:
        return found
    for p in (Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tailscale" / "tailscale.exe",
              Path("/Applications/Tailscale.app/Contents/MacOS/Tailscale")):
        if p.exists():
            return str(p)
    return None


def tailscale_ip():
    """This computer's Tailscale IPv4 address, or None if Tailscale isn't installed and connected."""
    cli = _tailscale_cli()
    if cli:
        try:
            out = subprocess.run([cli, "ip", "-4"], capture_output=True, text=True, timeout=5,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
            for line in out.split():
                if _is_tailnet(line):
                    return line
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            if _is_tailnet(info[4][0]):
                return info[4][0]
    except OSError:
        pass
    return None


def _is_tailnet(ip):
    try:
        return ipaddress.ip_address(ip) in TAILNET
    except ValueError:
        return False


def tailscale_name():
    """This computer's Tailscale name (e.g. 'my-laptop'), for a friendlier link; None if unknown."""
    cli = _tailscale_cli()
    if not cli:
        return None
    try:
        out = subprocess.run([cli, "status", "--json"], capture_output=True, text=True, timeout=5,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        return (json.loads(out).get("Self", {}).get("HostName") or None)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


# ---------------------------------------------------------------------------
# What a message does
# ---------------------------------------------------------------------------

def check_pin(given):
    """True if the PIN is right. Wrong ones count towards a lock-out."""
    now = time.time()
    with _lock:
        if now < _fails["until"]:
            return False
        if pin() and hmac.compare_digest(str(given or ""), pin()):
            _fails["n"] = 0
            return True
        _fails["n"] += 1
        if _fails["n"] >= MAX_FAILS:
            _fails.update(n=0, until=now + LOCK_SECONDS)
        return False


def locked():
    return time.time() < _fails["until"]


def say(text):
    """Send a phone message to Claude; returns {reply, pending: [{id, summary}], error}."""
    from venato import assistant
    text = str(text or "").strip()
    if not text:
        return {"reply": "", "pending": [], "error": "Say something first."}
    turn = assistant.run_turn(f"(From my phone) {text}", list(_history), key="phone")
    with _lock:
        _history.extend([("user", text), ("assistant", turn.reply or turn.error or "")])
        del _history[:-2 * HISTORY]
        pending = []
        for p in turn.pending:
            pid = uuid.uuid4().hex
            _pending[pid] = p
            pending.append({"id": pid, "summary": p.summary})
    return {"reply": turn.reply, "pending": pending, "error": turn.error}


def confirm(pid, ok):
    from venato import tools
    with _lock:
        p = _pending.pop(pid, None)
    if not p:
        return {"reply": "That's already been dealt with."}
    if not ok:
        _history.append(("assistant", f"(The user cancelled: {p.summary}.)"))
        return {"reply": "Cancelled."}
    try:
        result = p.run()
    except tools.ToolError as e:
        return {"reply": "", "error": f"Couldn't do that: {e}"}
    _history.append(("assistant", f"(The user confirmed, and it was done: {p.summary}.)"))
    return {"reply": f"✓ {result.text}"}


def session_snapshot():
    """Today's Start Working list, for the phone page."""
    return [{"title": i["title"], "done": i["done"]} for i in store.session_items()]


# ---------------------------------------------------------------------------
# The web server
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "Venato"

    def log_message(self, *args):          # no request log on the console
        pass

    def _send(self, code, body, kind="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def _allowed_peer(self):
        return _is_tailnet(self.client_address[0]) or self.client_address[0] == "127.0.0.1"

    def do_GET(self):
        if not self._allowed_peer():
            return self._send(403, {"error": "Not allowed."})
        if self.path in ("/", "/index.html"):
            return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        if self.path == "/manifest.json":
            return self._send(200, {"name": "Venato", "short_name": "Venato", "start_url": "/",
                                    "display": "standalone", "background_color": "#0e1117",
                                    "theme_color": "#0e1117"}, "application/manifest+json")
        self._send(404, {"error": "Not found."})

    def do_POST(self):
        if not self._allowed_peer():
            return self._send(403, {"error": "Not allowed."})
        try:
            length = min(int(self.headers.get("Content-Length") or 0), 20000)
            body = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, OSError):
            return self._send(400, {"error": "Bad request."})
        if not check_pin(self.headers.get("X-Venato-Pin")):
            return self._send(401, {"error": "Locked for a few minutes: too many wrong PINs." if locked()
                                    else "Wrong PIN."})
        if self.path == "/api/check":
            return self._send(200, {"ok": True, "session": session_snapshot()})
        if self.path == "/api/say":
            out = say(body.get("text"))
            return self._send(200, {**out, "session": session_snapshot()})
        if self.path == "/api/confirm":
            out = confirm(body.get("id"), bool(body.get("ok")))
            return self._send(200, {**out, "session": session_snapshot()})
        self._send(404, {"error": "Not found."})


def status():
    """(address it's served at, or None; why not, or None)."""
    with _lock:
        if _server:
            return _server[1], None
    if not enabled():
        return None, "Switched off."
    return None, _why_not


_why_not = None
_retry = {"at": 0.0}
RETRY_SECONDS = 20


def ensure_running(force=False):
    """Start (or stop) the phone server to match the setting. Cheap to call on every page load."""
    global _server, _why_not
    if force:
        _retry["at"] = 0.0
    want = enabled() and bool(pin())
    with _lock:
        running = _server
    if running and not want:
        stop()
        return
    if running or not want:
        return
    if time.time() < _retry["at"]:          # Tailscale wasn't there a moment ago: don't ask on every click
        return
    _retry["at"] = time.time() + RETRY_SECONDS
    ip = tailscale_ip()
    if not ip:
        _why_not = "Tailscale isn't running on this computer."
        return
    try:
        httpd = ThreadingHTTPServer((ip, PORT), Handler)
    except OSError as e:
        _why_not = f"Couldn't listen on {ip}:{PORT} ({e})."
        return
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, name="venato-phone", daemon=True).start()
    with _lock:
        _server = (httpd, f"http://{ip}:{PORT}")
        _why_not = None


def stop():
    global _server
    with _lock:
        running, _server = _server, None
    if running:
        running[0].shutdown()
        running[0].server_close()


if __name__ == "__main__":       # python -m venato.phone: serve on localhost for testing
    PORT = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
