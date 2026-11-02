"""Static check: no undefined names anywhere (e.g. a module used without being imported),
which only fails when that exact line runs, so the other tests can miss it."""

from pathlib import Path

from pyflakes import api, messages, reporter

ROOT = Path(__file__).resolve().parents[1]


class Collect(reporter.Reporter):
    def __init__(self):
        self.found = []

    def flake(self, message):
        if isinstance(message, (messages.UndefinedName, messages.UndefinedLocal, messages.UndefinedExport)):
            self.found.append(f"{Path(message.filename).relative_to(ROOT)}:{message.lineno}: {message.message % message.message_args}")

    def unexpectedError(self, filename, msg):
        self.found.append(f"{filename}: {msg}")

    def syntaxError(self, filename, msg, lineno, offset, text):
        self.found.append(f"{filename}:{lineno}: {msg}")


def test_no_undefined_names():
    out = Collect()
    for path in [ROOT / "app.py", ROOT / "desktop.py", *sorted((ROOT / "venato").rglob("*.py"))]:
        api.checkPath(str(path), out)
    assert out.found == []
