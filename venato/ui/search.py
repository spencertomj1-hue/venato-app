"""
Search everything, from the top of the sidebar on every page: to-dos, goals,
deadlines, habits, the journal, timetable blocks, Outlook events and weekly reviews,
plus whatever the switched-on blocks add (Block.search). Each result's Open button goes
to the right page (and day); a block's results go where its search_open says. The
matching is store.search.
"""

from html import escape

import streamlit as st

from venato import regional
from venato import store

ICONS = {"To-do": "check_circle", "Goal": "flag", "Deadline": "event",
         "Timetable": "calendar_view_week", "Outlook": "calendar_month", "Review": "insights"}


def _icon(kind):
    from venato import blocks
    return ICONS.get(kind) or next((b.search_icons[kind] for b in blocks.enabled() if kind in b.search_icons), "search")


def _open(r):
    """Go to where a result lives."""
    kind, ss = r["kind"], st.session_state
    from venato import blocks
    owner = blocks.search_block(kind)
    if owner and owner.search_open:
        owner.search_open(r, ss)
    elif kind == "To-do":
        ss["page"] = "Home"
    elif kind in ("Goal", "Deadline"):
        ss["page"] = "Goals"
        if kind == "Goal":
            ss[f"goals_start_{r['extra']}"] = store._as_date(r["date"])
    elif kind in ("Timetable", "Outlook"):
        ss["page"] = "Timetable"
        ss["tt_day"] = store._as_date(r["date"])
    elif kind == "Review":
        ss["page"] = "Review"
        ss["review_week"] = store._as_date(r["date"])


def _snippet(text, words, width=90):
    """A short bit of text around the first match, with the matches in bold."""
    text = " ".join(str(text or "").split())
    low = text.lower()
    at = min((low.find(w.lower()) for w in words if w.lower() in low), default=0)
    start = max(0, at - 30)
    piece = ("…" if start else "") + text[start:start + width] + ("…" if start + width < len(text) else "")
    out = escape(piece)
    for w in sorted(set(words), key=len, reverse=True):
        lo = out.lower()
        i, parts = 0, []
        while (j := lo.find(escape(w).lower(), i)) >= 0:
            parts += [out[i:j], f"<b>{out[j:j + len(escape(w))]}</b>"]
            i = j + len(escape(w))
        out = "".join(parts) + out[i:]
    return out


def _when(r):
    if not r["date"]:
        return ""
    if r["kind"] == "Review":
        return "week of " + regional.day_month(r["date"], weekday=False)
    when = regional.day_month(r["date"], year=store._as_date(r["date"]).year != store.local_today().year)
    if r["kind"] == "Timetable" and r["extra"]:               # "plan 10:00-12:00" -> "Plan, 10:00–12:00"
        track, _, times = r["extra"].partition(" ")
        start, _, end = times.partition("-")
        when += f", {track.capitalize()} {regional.time_range(start, end)}"
    elif r["kind"] == "Outlook" and r["extra"]:
        when += f", {regional.time(r['extra'])}"
    return when


SHOW = 12          # results listed (the sidebar is narrow); more words narrow it down


def render_sidebar():
    query = st.text_input("Search everything", placeholder="Search",
                          label_visibility="collapsed", key="global_search", icon=":material/search:")
    if not query.strip():
        return
    results = store.search(query)
    if not results:
        st.caption(f"Nothing matches “{query.strip()}”.")
        return
    words = query.split()
    n = len(results)
    st.caption(f"{n} result{'s' * (n != 1)}" + (f", the first {SHOW} shown. Add a word to narrow it." if n > SHOW else ""))
    for i, r in enumerate(results[:SHOW]):
        text, detail = (r["detail"] or r["title"], r["title"]) if r["kind"] == "Review" else (r["title"], r["detail"])
        if r["kind"] == "Journal":
            text, detail = r["title"], None
        left, right = st.columns([3, 1], vertical_alignment="center", gap="small")
        left.html(
            f'<div style="font-size:0.85rem;line-height:1.35">'
            f'<span aria-hidden="true" style="font-family:\'Material Symbols Rounded\';font-size:1rem;vertical-align:-3px;opacity:.8">'
            f'{_icon(r["kind"])}</span> '
            f'<span style="opacity:.8">{escape(r["kind"])}{" · " + escape(_when(r)) if _when(r) else ""}'
            f'{" · " + escape(detail) if detail and r["kind"] == "Review" else ""}</span><br>'
            f'{_snippet(text, words, 60)}'
            f'{"<br><span style=opacity:.8>" + _snippet(detail, words, 60) + "</span>" if detail and r["kind"] != "Review" else ""}'
            f'</div>')
        right.button("Open", key=f"search_open_{i}_{r['kind']}_{r['id']}", on_click=_open, args=(r,),
                     type="tertiary", help=f"Open this {r['kind'].lower()}")
