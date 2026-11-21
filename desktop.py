"""
Desktop launcher: runs the Streamlit app in its own native window (no browser).

Run with:   .venv/bin/python desktop.py          (macOS / Linux)
            .venv/Scripts/pythonw.exe desktop.py  (Windows)
Or open "Venato.app" (macOS) or the Venato shortcut (Windows), made by setup.sh / setup.ps1.

It's also the entry point of the packaged Windows app (Venato.exe, built by
packaging/venato.spec). A packaged app has no separate Python to run Streamlit
with, so it starts a second copy of itself with `--serve PORT` to be the server.
`Venato.exe --check` imports everything and sets up a database, then exits with
0 if all is well (the release build uses it as a smoke test).
"""

import atexit
import base64
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)          # running as the packaged Venato.exe
APP_DIR = Path(sys._MEIPASS) if FROZEN else Path(__file__).parent
ICON = APP_DIR / "assets" / "icon.png"   # built by scripts/make_icon.py
SPLASH_LOGO = APP_DIR / "assets" / "splash.png"   # also built by scripts/make_icon.py
SPLASH_SECONDS = 0.6                     # minimum time the loading screen shows
READY_TIMEOUT = 45                       # give up waiting for the page after this (it shows anyway)
SETTLE_SECONDS = 0.4                     # the page must hold still this long before the splash lifts
# A fingerprint of the page: while it changes (components still mounting, text still reflowing) it isn't settled.
SETTLED_JS = """(() => {
  if (!document.getElementById('venato-ready') || !document.fonts || document.fonts.status !== 'loaded') return '';
  const b = document.body;
  return [b.scrollHeight, b.getBoundingClientRect().width, document.querySelectorAll('*').length,
          document.querySelectorAll('[data-stale="true"]').length, document.querySelectorAll('.blk').length,
          document.querySelectorAll('.tt-root').length].join(',');
})()"""


def _data_dir():
    from venato import system
    return system.data_dir()


def _window_colour():
    """The window's colour before the page draws: dark if Venato is set to dark mode, so it doesn't flash white."""
    import json
    try:
        theme = json.loads((_data_dir() / "settings.json").read_text(encoding="utf-8")).get("theme")
    except (OSError, ValueError):
        theme = None
    return "#0E1117" if theme == "Dark" else "#FFFFFF"


def splash_html():
    """splash.html with the logo embedded, so it shows before the server is up."""
    logo = base64.b64encode(SPLASH_LOGO.read_bytes()).decode()
    return (APP_DIR / "assets" / "splash.html").read_text(encoding="utf-8").replace("{{LOGO}}", f"data:image/png;base64,{logo}")


def set_dock_icon():
    """The running process is Python, so tell macOS to show Venato's name and icon instead."""
    try:
        from AppKit import NSApplication, NSImage
        from Foundation import NSBundle
        info = NSBundle.mainBundle().infoDictionary()
        if info is not None:
            info["CFBundleName"] = "Venato"      # menu bar / Dock name
        image = NSImage.alloc().initWithContentsOfFile_(str(ICON))
        if image:
            NSApplication.sharedApplication().setApplicationIconImage_(image)
    except Exception:
        pass  # cosmetic only


def quiet_output():
    """A windowed Venato.exe has no console, so send output to a log file in the data folder."""
    if sys.stdout is None or sys.stderr is None:
        from venato import system
        logs = system.data_dir() / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        log = open(logs / "venato.log", "a", encoding="utf-8", buffering=1)   # noqa: SIM115 - lives as long as the app
        sys.stdout = sys.stdout or log
        sys.stderr = sys.stderr or log


def serve(port):
    """Run the Streamlit server in this process (the packaged app's server copy)."""
    quiet_output()
    os.chdir(APP_DIR)                     # Streamlit reads .streamlit/config.toml from here
    from streamlit.web import cli as streamlit_cli
    sys.argv = ["streamlit", "run", str(APP_DIR / "app.py"), *server_flags(port),
                "--global.developmentMode", "false"]
    sys.exit(streamlit_cli.main())


def check_arrow():
    """Serialise a small table the way st.dataframe does. AppTest never does, so without this a missing pyarrow
    module or library (the packaging/venato.spec excludes) would pass `--check` and break every table on screen."""
    import pandas as pd
    from streamlit import dataframe_util
    import pyarrow.lib, pyarrow.compute, pyarrow.ipc  # noqa: F401,E401  (what Streamlit's dataframe path loads)
    frame = pd.DataFrame({"n": [1, 2], "s": ["a", "b"], "d": pd.to_datetime(["2026-01-01", "2026-01-02"])})
    if not dataframe_util.convert_pandas_df_to_arrow_bytes(frame):
        raise RuntimeError("pyarrow produced nothing")


def check():
    """
    Run the real app, headless, on a throwaway data folder and open every page
    (Streamlit's AppTest): exits 0 only if every page draws without an error.
    The release build runs this inside the bundle, so a missing module or data
    file fails the build instead of the user's first launch.
    """
    quiet_output()
    import json
    import tempfile
    data = Path(os.environ.setdefault("VENATO_DATA_DIR", tempfile.mkdtemp(prefix="venato-check-")))
    data.mkdir(parents=True, exist_ok=True)
    from venato import blocks
    every_block = [b.key for b in blocks.all_blocks()]       # every page
    (data / "settings.json").write_text(json.dumps({"wizard_done": True, "blocks": every_block}), encoding="utf-8")
    try:
        check_arrow()
    except Exception as e:
        print(f"Venato check FAILED:\ntables (pyarrow): {type(e).__name__}: {e}")
        sys.exit(1)
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(APP_DIR / "app.py"), default_timeout=180).run()
    from venato.ui import nav
    pages = list(nav.pages())
    problems = [f"Home: {e.message}" for e in at.exception]
    for page in pages[1:]:
        at.session_state["page"] = page
        at.run()
        problems += [f"{page}: {e.message}" for e in at.exception]
    if problems or not pages:
        print("Venato check FAILED:\n" + ("\n".join(problems) or "the app didn't draw its menu"))
        sys.exit(1)
    print(f"Venato check OK: {len(pages)} pages drawn")


def server_flags(port):
    return ["--server.headless", "true", "--server.port", str(port),
            "--server.address", "127.0.0.1", "--browser.gatherUsageStats", "false"]


def free_port():
    """Ask the OS for an unused port so we never clash with another app."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_server(port, timeout=30):
    """Block until Streamlit is accepting connections."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.2)
    raise RuntimeError("Streamlit didn't start in time")


def main():
    import webview            # only the window process needs the GUI toolkit (not --serve / --check)

    port = free_port()

    # Start Streamlit in the background without opening a browser tab (or, on
    # Windows, a console window).
    if FROZEN:
        command = [sys.executable, "--serve", str(port)]
    else:
        command = [sys.executable, "-m", "streamlit", "run", str(APP_DIR / "app.py"), *server_flags(port)]
    server = subprocess.Popen(command, cwd=APP_DIR,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def stop_server():
        if server.poll() is None:
            server.terminate()

    # Make sure the server stops however the app exits (closing the window,
    # Cmd+Q, or the process being killed).
    atexit.register(stop_server)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    def show_app(splash):
        """
        Runs once the splash is up. The app window opens maximised straight away, behind the
        splash (which stays on top), so the whole page loads and lays out under the cover.
        Once it has settled and the splash has had SPLASH_SECONDS, the splash fades out
        to reveal the finished app, and closes.
        """
        shown_at = time.time()
        try:
            wait_for_server(port)
        except RuntimeError:
            return show_error(splash)

        # Maximised and visible from the start: it loads behind the splash, so it lays out once, at full size.
        app = webview.create_window(
            "Venato", f"http://127.0.0.1:{port}", width=1200, height=850, maximized=True,
            background_color=_window_colour(),
        )
        app.events.closed += stop_server
        state["app"] = app

        # Wait until the page has drawn everything and stopped moving (its ready marker is in, the
        # fonts are loaded, and its layout has been the same for a moment), then fade the splash.
        deadline = time.time() + READY_TIMEOUT
        last, still_since = None, time.time()
        while time.time() < deadline:
            try:
                ready = app.evaluate_js(SETTLED_JS)
                if ready and ready != last:
                    last, still_since = ready, time.time()
                if ready and time.time() - still_since >= SETTLE_SECONDS:
                    break
                if not ready:
                    last, still_since = None, time.time()
            except Exception:
                pass            # page not loaded yet
            time.sleep(0.1)

        time.sleep(max(0.0, SPLASH_SECONDS - (time.time() - shown_at)))
        state["swapped"] = True                                     # closing the splash now is fine: the app stays
        splash.evaluate_js("document.body.classList.add('out')")    # fade the splash, revealing the app
        time.sleep(0.45)
        splash.destroy()

    def show_error(splash):
        splash.evaluate_js(
            "document.getElementById('motto').outerHTML ="
            " '<p class=\"error\">Venato couldn\\'t start. Close this window and try again.</p>'"
        )

    state = {"app": None, "swapped": False}

    def splash_closed():
        # Closing the splash before the app appears means quitting.
        if not state["swapped"]:
            stop_server()
            if state["app"]:
                state["app"].destroy()

    try:
        splash = webview.create_window(
            "Venato", html=splash_html(), width=1200, height=850,
            maximized=True, background_color="#FFFFFF",
            on_top=True,                                 # stays in front while the app loads behind it
        )
        splash.events.closed += splash_closed
        set_dock_icon()
        # Not private: the window keeps its browser storage (e.g. the light/dark choice) between launches.
        webview.start(show_app, splash, private_mode=False,
                      storage_path=str(_data_dir() / "webview"))  # blocks until every window is closed
    finally:
        stop_server()


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--serve":
        serve(int(sys.argv[2]))
    elif len(sys.argv) > 1 and sys.argv[1] == "--check":
        check()
    else:
        quiet_output()
        main()
