"""scripts/seed_demo.py runs against the current schema and fills a new folder."""

import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_seed_demo_runs_on_a_new_folder(tmp_path):
    folder = tmp_path / "demo"
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / "seed_demo.py"), str(folder)],
                         capture_output=True, text=True, timeout=120, cwd=ROOT)
    assert out.returncode == 0, out.stderr
    assert "Demo data created" in out.stdout
    con = sqlite3.connect(next(folder.glob("*.db")))
    count = lambda t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]   # noqa: E731
    assert count("gr_modules") == 2 and count("deadlines") == 3 and count("goals") >= 5
    assert count("entries") > 20 and count("tt_outlook") > 0
    assert con.execute("SELECT COUNT(*) FROM tt_outlook WHERE module_id IS NOT NULL").fetchone()[0] > 0
    assert con.execute("SELECT COUNT(*) FROM goals WHERE deadline_id IS NOT NULL").fetchone()[0] == 1
