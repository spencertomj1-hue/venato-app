"""
Home: today's agenda and timetable on the left; on the right the assistant box, then each
switched-on block's widget in the order of your priorities (Settings → Blocks), then search.
"""

from html import escape

import streamlit as st

from venato import regional
from venato import store
from venato.ui import chat
from venato.ui import search
from venato.ui import timetable


def _agenda():
    """Today's plan (own blocks and Outlook events) as a short list, the current one highlighted."""
    today = store.local_today().isoformat()
    blocks = [{**b, "outlook": False} for b in store.blocks_between(today, today, "plan")]
    all_day = []
    if st.session_state.get("tt_show_outlook", True):
        for ev in store.outlook_between(today, today):
            if ev["all_day"]:
                all_day.append(ev["title"])
            else:
                blocks.append({"start": ev["start"], "end": ev["end"], "label": ev["title"], "outlook": True,
                               "category_id": store.outlook_category(ev["title"]), "exact": ev["exact"]})
    all_day += [f"Due: {d['title']}" for d in store.deadlines() if d["due"] == today]
    blocks.sort(key=lambda b: store.slot_of(b["start"]))
    colours = dict(zip(*[store.load_categories()[c] for c in ("id", "colour")]))
    now = store.local_now()
    now_slot = store.slot_of(f"{now:%H}:{now.minute // 30 * 30:02d}")

    rows = []
    for b in blocks:
        current = store.slot_of(b["start"]) <= now_slot < store.slot_of(b["end"])
        rows.append(
            f'<div class="ag-row{" now" if current else ""}">'
            f'<span class="ag-dot" style="background:{colours.get(b["category_id"], "#999")}"></span>'
            f'<span class="ag-time">{regional.times_in(b["exact"]) if b["outlook"] else regional.time_range(b["start"], b["end"])}</span>'
            f'<span class="ag-label">{escape(b["label"])}'
            f'{" <span class=ag-ol title=Outlook>Outlook</span>" if b["outlook"] else ""}</span>'
            f'{"<span class=ag-now>Now</span>" if current else ""}</div>'
        )
    chips = "".join(f'<span class="ag-chip">{escape(t)}</span>' for t in all_day)
    body = (f'<div class="ag-chips">{chips}</div>' if chips else "") + (
        "".join(rows) or '<div class="ag-empty">Nothing planned for today yet.</div>')
    st.html(f"""<style>
      .ag {{ margin-bottom: 10px; max-height: 16vh; overflow-y: auto; }}   /* long days scroll inside */
      .ag h3 {{ margin: 0 0 4px; font-size: 1.05rem; font-weight: 600; }}
      .ag-row {{ display: flex; align-items: center; gap: 10px; padding: 2px 8px; border-radius: 7px; font-size: 0.86rem; }}
      .ag-row.now {{ background: rgba(128, 128, 128, 0.12); font-weight: 600; }}
      .ag-dot {{ width: 9px; height: 9px; border-radius: 3px; flex: none; }}
      .ag-time {{ min-width: 6.5em; white-space: nowrap; flex: none; opacity: 0.8; font-variant-numeric: tabular-nums; }}
      .ag-label {{ min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
      .ag-now {{ margin-left: auto; font-size: 0.72rem; font-weight: 600; color: #ff4b4b; }}
      .ag-empty {{ opacity: 0.78; font-size: 0.86rem; }}
      .ag-ol {{ margin-left: 6px; padding: 0 6px; border: 1px solid rgba(128,128,128,.45); border-radius: 999px;
                font-size: 0.64rem; font-weight: 500; opacity: 0.75; }}
      .ag-chips {{ display: flex; flex-wrap: wrap; gap: 4px; margin: 0 0 4px; }}
      .ag-chip {{ padding: 1px 8px; border: 1px dashed rgba(128,128,128,.6); border-radius: 999px; font-size: 0.75rem; }}
    </style><div class="ag"><h3>Agenda</h3>{body}</div>""")


def page_home():
    """Agenda + today's Plan / Actual on the left (if the timetable is on); on the right the
    Ask box, then every switched-on block's widget in priority order, then search."""
    from venato import blocks
    widgets = [b.home for b in blocks.enabled() if b.home]
    if blocks.is_on("timetable"):
        left, right = st.columns([2, 3], gap="large")
        with left:
            _agenda()
            timetable.render_today()
        columns = [right]
    else:
        right = None
        columns = list(st.columns(2, gap="large"))
    if store.ai_enabled():
        with columns[0]:
            chat.render(inline=True)
    for i, widget in enumerate(widgets):
        with columns[i % len(columns)]:
            try:
                widget()
            except Exception as e:               # one broken widget mustn't take Home down with it
                st.caption(f":material/error: A Home widget couldn't load ({type(e).__name__}).")
    with columns[-1]:
        search.render_home()                     # search everything (bottom right)
