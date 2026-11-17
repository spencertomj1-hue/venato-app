"""
Reads remembered until the data changes. No UI: pace.py, tools.py and the notify thread use it too.

`cached(fn)` wraps fn in st.cache_data (works with or without a running Streamlit app). Its hidden key is
the database file, store.data_version() (up on every write made through store.db(), save_settings and
undo.restore), settings.json's mtime and size (hand edits), and today's date.
"""

import functools
import logging

import streamlit as st
from streamlit import runtime

from venato import store

if not runtime.exists():     # scripts and tests: no "No runtime found" warning from Streamlit's cache
    logging.getLogger("streamlit.runtime.caching.cache_data_api").setLevel(logging.ERROR)


def cache_key():
    """What a cached read depends on besides its arguments: which database, how many writes it has seen,
    settings.json (edited by hand too), and today's date (so "today" can't go stale past midnight)."""
    try:
        stat = store.settings_path().stat()
        settings = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        settings = None
    return str(store.DB_PATH), store.data_version(), settings, store.local_today().isoformat()


def cached(fn):
    """Remember fn's answer until the data changes. Same signature as fn; the answer is copied on every
    call, so callers may change what they get. Return values must be picklable (data, not connections)."""
    def body(key, *args, **kwargs):          # `key` is hashed (no leading underscore): it is the point
        return fn(*args, **kwargs)
    body.__module__, body.__qualname__ = fn.__module__, f"{fn.__qualname__}#{id(fn)}"   # one cache per function
    remembered = st.cache_data(max_entries=64, show_spinner=False)(body)

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return remembered(cache_key(), *args, **kwargs)
    return wrapper
