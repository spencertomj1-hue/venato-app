"""Windows' strftime doesn't know %-d / %-I etc. (Linux and Mac do, so it only fails there):
Python code must use store.fmt_day instead. Plotly's tickformat / hoverformat are fine (d3, in the browser)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_no_platform_specific_strftime():
    bad = []
    for f in [ROOT / "app.py", *sorted((ROOT / "venato").rglob("*.py"))]:
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#")[0]
            if re.search(r"%-[a-zA-Z]", code) and not re.search(r"tickformat|hoverformat|fmt_day|fmt\.replace", code):
                bad.append(f"{f.relative_to(ROOT)}:{n}: {line.strip()}")
    assert not bad, "Use store.fmt_day (Windows has no %-d):\n" + "\n".join(bad)


def test_fmt_day():
    from datetime import date
    from venato import store
    assert store.fmt_day(date(2026, 11, 7)) == "Sat 7 Nov"
    assert store.fmt_day("2026-11-07", "%-d %b %Y") == "7 Nov 2026"
