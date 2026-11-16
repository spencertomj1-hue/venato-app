"""
"Let Claude edit the app": when switched on (Settings → Claude), the chat's Claude
also gets Claude Code's own tools (read, edit and write files, search, run commands)
in the app's folder, so it can change anything about Venato, not just the data.

Safety net: every chat message that changes code is saved as its own git commit
("Venato chat: <the request>"), so Settings can undo it (git revert). Only the files
that message changed are committed, never other work in progress.

Only available when Venato runs from a git clone (not the packaged installers,
whose code is bundled and read-only).
"""

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

from venato import store

APP_DIR = Path(__file__).resolve().parents[1]
COMMIT_PREFIX = "Venato chat: "
CODE_TOOLS = ["Read", "Edit", "Write", "Glob", "Grep", "Bash"]


def available():
    """Why not, or None if Claude can edit the code here."""
    if getattr(sys, "frozen", False):
        return "This copy of Venato was installed from a download, so its code can't be edited. Run it from the source folder instead."
    if not (APP_DIR / ".git").exists():
        return "Venato's folder isn't a git repository, so changes couldn't be undone."
    if not shutil.which("git"):
        return "git isn't installed, so changes couldn't be undone."
    return None


def enabled():
    return bool(store.load_settings().get("claude_edits_code")) and available() is None


def set_enabled(on):
    store.save_settings(claude_edits_code=bool(on))


def _git(*args, check=False):
    return subprocess.run(["git", *args], cwd=APP_DIR, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=check)


def snapshot():
    """{path: content hash} of every changed or untracked file, to compare after a message."""
    out = _git("status", "--porcelain", "-z", "--untracked-files=all").stdout
    state = {}
    for item in filter(None, out.split("\0")):
        path = item[3:]
        if not path or item[:2] == "R ":
            continue
        f = APP_DIR / path
        state[path] = hashlib.sha1(f.read_bytes()).hexdigest() if f.is_file() else None
    return state


def changed_since(before):
    """Files whose content differs from the snapshot (new, edited, deleted or restored)."""
    after = snapshot()
    return sorted(p for p in set(before) | set(after) if before.get(p, "clean") != after.get(p, "clean"))


def commit(paths, request):
    """Commit just these files as one undoable change. Returns the short hash, or None."""
    if not paths:
        return None
    for path in paths:
        _git("add", "-A", "--", path)
    message = COMMIT_PREFIX + " ".join(request.split())[:70]
    args = ["commit", "-m", message, "--only", "--", *paths]
    if not _git("config", "user.email").stdout.strip():
        args = ["-c", "user.name=Venato", "-c", "user.email=venato@localhost", *args]
    result = _git(*args)
    if result.returncode != 0:
        return None
    return _git("rev-parse", "--short", "HEAD").stdout.strip()


def history(limit=5):
    """[(hash, subject, when)] of recent chat code changes."""
    out = _git("log", f"-{limit}", "--grep", f"^{COMMIT_PREFIX}", "--format=%h%x09%s%x09%cr").stdout
    return [tuple(line.split("\t", 2)) for line in out.splitlines() if line.count("\t") == 2]


def undo(commit_hash):
    """Revert one chat change. Returns (ok, message)."""
    result = _git("revert", "--no-edit", commit_hash)
    if result.returncode != 0:
        _git("revert", "--abort")
        return False, ("Couldn't undo it automatically: later changes touch the same lines. "
                       "Ask Claude (with editing on) to undo it instead.")
    return True, "Undone. Restart Venato if the change was outside app.py."


def system_prompt():
    return f"""
Editing the app itself
The user has switched on "Let Claude edit the app", so you can also change Venato's own code, not just
their data: new pages, features, layout, behaviour, fixes. You have Read, Edit, Write, Glob, Grep and Bash,
working in the app's folder: {APP_DIR}
- Before changing code, read HANDOVER.md (how the app is built, and its pitfalls) and the files involved.
- Keep to the existing style: all SQL in venato/store.py, one module per page in venato/ui/, plain Python.
- After changing code, run the tests: "{Path(sys.executable)}" -m pytest -q -p no:logging tests
  and fix anything you broke. Never test against the user's real data folder ({store.DATA_DIR}).
- Don't run git commit, push or reset: Venato saves each message's code changes as a commit itself, which the
  user can undo in Settings → Claude.
- For data changes, still use the venato tools, not SQL on the database.
- When done, say in a sentence or two what you changed. Changes to app.py show straight away; changes to other
  files show after the page reloads (Venato does that for you after this message).
- Never edit files outside the app folder, install software, or touch the user's secrets.
"""
