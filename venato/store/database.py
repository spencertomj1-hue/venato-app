"""
Where the data lives, and the one way in: db() opens a connection to it.

All user data lives in the data folder (system.default_data_dir(): ~/Library/Application Support/Venato
on a Mac, %APPDATA%/Venato on Windows, ~/.local/share/Venato on Linux), or $VENATO_DATA_DIR, used for
tests and the demo). The database is life.db there (or $VENATO_DB). Backups, settings.json and the
Outlook cache live there too. Nothing user-specific is kept in the project folder.
"""

import functools
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

from venato import system


def data_dir():
    """The data folder (system.data_dir), worked out once per $VENATO_DATA_DIR value."""
    return _data_dir(system.env("DATA_DIR"))


@functools.cache
def _data_dir(_chosen):
    return system.data_dir()          # (copies an old Arete data folder across the first time)


_db_override = None


def db_path():
    """The database file: $VENATO_DB, else life.db in the data folder (unless use_db_path chose another)."""
    return _db_override or _default_db_path()


def _default_db_path():
    return Path(system.env("DB") or data_dir() / "life.db")


def use_db_path(path):
    """Use another database file (tests do, by setting store.DB_PATH); None goes back to the usual one."""
    global _db_override
    _db_override = Path(path) if path is not None else None


_version = 0


_version_lock = threading.Lock()      # the Outlook sync and reminder threads write too


def data_version():
    """A number that goes up whenever the database (or settings.json) is written: what cached reads
    are keyed on (see kit.cached). Process-wide; anything that writes the live database outside db()
    must call bump_version()."""
    return _version


def bump_version():
    global _version
    with _version_lock:
        _version += 1


@contextmanager
def db():
    """Open a connection, commit on success, and always close it."""
    conn = sqlite3.connect(db_path())
    conn.execute("PRAGMA foreign_keys = ON")  # needed for ON DELETE CASCADE
    try:
        yield conn
        conn.commit()
        if conn.total_changes:
            bump_version()
    finally:
        conn.close()


def _read(sql, params=()):
    """Run a query into a DataFrame, with SQL NULLs as None (NaN isn't valid JSON)."""
    with db() as conn:
        df = pd.read_sql(sql, conn, params=params)
    return df.astype(object).where(df.notna(), None)


KEEP = object()   # e.g. save_entry(water=KEEP), update_goal: leave this field as it is
