"""
Time how long each Venato page (and a few widget interactions) takes to rerun.

    .venv/bin/python scripts/profile_pages.py                       # every page, 5 runs each
    .venv/bin/python scripts/profile_pages.py --runs 9 --pages Home,Timetable

It builds a throwaway data folder (never your real one) filled by scripts/seed_demo.py, switches every
block on, and drives app.py with Streamlit's AppTest. For each page it sets the page, discards the
first run (cold: imports, first draw) and reports the median and 90th percentile of the rest, in ms.
Interactions are listed after the pages. Results go in docs/perf.md.
"""

import argparse
import atexit
import logging
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Set up the throwaway data folder before any venato module is imported.
FOLDER = Path(tempfile.mkdtemp(prefix="venato-profile-"))
atexit.register(shutil.rmtree, FOLDER, ignore_errors=True)
DATA = FOLDER / "data"
subprocess.run([sys.executable, str(ROOT / "scripts" / "seed_demo.py"), str(DATA)],
               check=True, stdout=subprocess.DEVNULL)
os.environ["VENATO_DATA_DIR"] = str(DATA)
os.environ.pop("VENATO_DB", None)
os.environ["VENATO_NO_REMINDERS"] = "1"          # no reminder thread
os.environ.pop("ANTHROPIC_API_KEY", None)
sys.path.insert(0, str(ROOT))

from streamlit.testing.v1 import AppTest  # noqa: E402

logging.disable(logging.WARNING)     # "missing ScriptRunContext" noise from bare runs

from venato import blocks, store  # noqa: E402

store.save_settings(wizard_done=True, blocks=[b.key for b in blocks.all_blocks()],
                    ai_enabled=False, update_check=False)

APP = str(ROOT / "app.py")


def new_app():
    return AppTest.from_file(APP, default_timeout=120)


def timed(fn):
    start = time.perf_counter()
    fn()
    return (time.perf_counter() - start) * 1000


def stats(samples):
    s = sorted(samples)
    p90 = s[min(len(s) - 1, int(round(0.9 * (len(s) - 1))))]
    return statistics.median(s), p90


def time_page(name, runs):
    at = new_app()
    at.session_state["page"] = name
    samples = []
    for i in range(runs + 1):
        ms = timed(at.run)
        if at.exception:
            return None, f"raised {at.exception[0].value[:60]!r}"
        if i:                                     # the first run is cold
            samples.append(ms)
    return samples, None


# --- interactions: each returns (setup(at), action(at)); the action is what's timed ---

def _fresh(page):
    at = new_app()
    at.session_state["page"] = page
    at.run()
    return at


def todo_tick(page="Home"):
    """The to-do list is a browser component, so AppTest can't click it: save the tick as the
    component's callback would (store), then time the rerun that follows."""
    today = store.local_today()
    for i in range(3):                              # the demo data has none for today
        store.add_todo(f"Profile task {i}", "daily", today)
    at = _fresh(page)
    todo = store.todos_for("daily", today)[0]
    state = {"done": bool(todo["done"])}

    def act():
        state["done"] = not state["done"]
        store.set_todo_done(todo["id"], state["done"])
        at.run()
    return at, act


def habit_tick(page, prefix):
    at = _fresh(page)
    boxes = [c for c in at.checkbox if c.key and c.key.startswith(prefix)]
    box = boxes[0]
    state = {"v": box.value}

    def act():
        state["v"] = not state["v"]
        box.set_value(state["v"]).run()
    return at, act


def focus_start(page="Home"):
    """Start from Home's quick-focus button (a real widget). The timer is stopped (untimed) before each go."""
    from venato.blocks import focus
    at = _fresh(page)

    def prep():
        if focus.running():
            focus.stop()
            at.run()

    def act():
        at.button(key="home_focus_go").click().run()
    return at, act, prep


def focus_stop(page="Home"):
    """Stopping is a browser-component action AppTest can't send, so stop in the store (untimed start
    first) and time the rerun that follows."""
    from venato.blocks import focus
    at = _fresh(page)

    def prep():
        if not focus.running():
            at.button(key="home_focus_go").click().run()

    def act():
        focus.stop()
        at.run()
    return at, act, prep


INTERACTIONS = [
    ("Home: tick a to-do", lambda: todo_tick("Home")),
    ("Daily Log: tick a habit", lambda: habit_tick("Daily Log", "habit_")),
    ("Home: tick a habit", lambda: habit_tick("Home", "home_habit_")),
    ("Focus: start (Home)", focus_start),
    ("Focus: stop (rerun after)", focus_stop),
]
NA = [
    ("Timetable: Plan / Actual switch", "n/a: the switch lives in the browser and never reruns Python"),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--runs", type=int, default=5, help="timed runs per page, after one discarded cold run")
    ap.add_argument("--pages", default="", help="comma-separated page names (default: all)")
    ap.add_argument("--no-interactions", action="store_true")
    args = ap.parse_args()

    pages = blocks_pages()
    if args.pages:
        wanted = [p.strip() for p in args.pages.split(",") if p.strip()]
        bad = [p for p in wanted if p not in pages]
        if bad:
            sys.exit(f"Unknown page(s): {', '.join(bad)}. Pages: {', '.join(pages)}")
        pages = wanted

    print(f"data folder: {DATA}  (runs per page: {args.runs}, first discarded)\n")
    print(f"{'page':<28}{'median_ms':>10}{'p90_ms':>10}")
    for name in pages:
        samples, err = time_page(name, args.runs)
        if err:
            print(f"{name:<28}{'n/a':>10}  {err}")
        else:
            med, p90 = stats(samples)
            print(f"{name:<28}{med:>10.0f}{p90:>10.0f}")

    if not args.no_interactions:
        print(f"\n{'interaction':<34}{'median_ms':>10}{'p90_ms':>10}")
        for name, build in INTERACTIONS:
            try:
                at, act, *rest = build()
                prep = rest[0] if rest else (lambda: None)
                samples = []
                for i in range(args.runs + 1):
                    prep()
                    ms = timed(act)
                    if at.exception:
                        raise RuntimeError(at.exception[0].value[:60])
                    if i:
                        samples.append(ms)
                med, p90 = stats(samples)
                print(f"{name:<34}{med:>10.0f}{p90:>10.0f}")
            except Exception as e:            # one failing interaction mustn't hide the rest
                print(f"{name:<34}{'n/a':>10}  {type(e).__name__}: {e}")
        for name, why in NA:
            print(f"{name:<34}{'n/a':>10}  {why}")


def blocks_pages():
    return ["Home", *blocks.pages(), "Settings"]


if __name__ == "__main__":
    main()
