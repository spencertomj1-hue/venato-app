"""
Shared look for the block pages: cards, stat tiles, charts, tables, progress rings and pills,
so Money, Food, Workouts, Grades, Involvement and Health all read as one app.

Everything is built from Streamlit's own pieces (bordered containers, st.metric, st.dataframe,
Plotly) plus a little HTML for rings and pills, and works in light and dark mode.
"""

from contextlib import contextmanager
from html import escape

import pandas as pd
import streamlit as st

from venato.ui import appearance

# One colour per category, the same on every chart: Tableau 10 without its red, which means
# "over" / "bad" here. Distinct, and readable on light and dark backgrounds.
PALETTE = ["#4E79A7", "#F28E2B", "#59A14F", "#8CD17D", "#76B7B2", "#EDC948", "#B07AA1", "#FF9DA7", "#9C755F",
           "#BAB0AC"]
GRID = "rgba(128,128,128,0.15)"
TRACK = "rgba(128,128,128,0.18)"


def colours(names):
    """{name: colour}, stable for a given order of names."""
    return {n: PALETTE[i % len(PALETTE)] for i, n in enumerate(names)}


def good_bad():
    """(good, bad) colours readable on the current background."""
    return ("#4ADE80", "#FF7B72") if appearance.is_dark() else ("#146C2E", "#C62828")


def amber():
    return "#FBBF24" if appearance.is_dark() else "#B45309"


def rgba(hex_colour, alpha):
    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r},{g},{b},{alpha})"


# --- Layout ---

@contextmanager
def card(title=None, caption=None, stretch=True):
    """A bordered card with a bold title. Cards side by side in st.columns stretch to the same height."""
    with st.container(border=True, height="stretch" if stretch else "content"):
        if title:
            st.markdown(f"**{title}**")
        if caption:
            st.caption(caption)
        yield


def section(title, caption=None):
    """A heading for a group of cards."""
    st.subheader(title, anchor=False)
    if caption:
        st.caption(caption)


def stats(items, per_row=None):
    """A row of bordered stat tiles. items: dicts with label, value and optionally delta, delta_color,
    help, chart (a list of numbers for a sparkline), chart_type. per_row keeps a short last row the same width."""
    cols = st.columns(per_row or len(items))
    for col, it in zip(cols, items):
        col.metric(it["label"], it["value"], it.get("delta"), it.get("delta_color", "normal"), border=True,
                   height="stretch",
                   help=it.get("help"), chart_data=it.get("chart") if it.get("chart") and any(it["chart"]) else None,
                   chart_type=it.get("chart_type", "area"), delta_arrow=it.get("delta_arrow", "auto"))


def empty(text, icon=":material/inbox:"):
    """A friendly empty state inside a card."""
    st.caption(f"{icon} {text}")


# --- Charts ---

def chart(fig, key, height=280, legend=False):
    """Draw a Plotly figure in the app's chart style: transparent, tight, quiet gridlines, no toolbar."""
    fig.update_layout(height=height, margin=dict(l=0, r=0, t=8, b=0), paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)", showlegend=legend, hoverlabel=dict(namelength=-1),
                      legend=dict(orientation="h", y=-0.15, x=0, title=None), bargap=0.25)
    fig.update_xaxes(showgrid=False, title=None)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, title=None)
    st.plotly_chart(fig, width="stretch", key=key, config={"displayModeBar": False})


# --- Tables ---

def table(rows, money=(), fmt=None, progress=(), dates=None, numbers=None, height=None, key=None):
    """A read-only table. money: columns shown with mn.fmt (or `fmt`), right-aligned. progress: 0..1
    columns drawn as bars with a %. dates: {column: format}. numbers: {column: printf format}."""
    df = pd.DataFrame(rows)
    if df.empty:
        return
    df = df.dropna(axis=1, how="all")          # a column with nothing in it is just noise
    cfg = {}
    money, progress = [c for c in money if c in df], [c for c in progress if c in df]
    for c in money:
        df[c] = df[c].map(lambda v: "" if v is None or v != v else fmt(v))
        cfg[c] = st.column_config.TextColumn(alignment="right")
    for c in progress:
        df[c] = df[c] * 100
        cfg[c] = st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100)
    for c, f in (dates or {}).items():
        cfg[c] = st.column_config.DateColumn(format=f)
    for c, f in (numbers or {}).items():
        cfg[c] = st.column_config.NumberColumn(format=f)
    st.dataframe(df, hide_index=True, width="stretch", column_config=cfg, key=key,
                 **({"height": height} if height else {}))


# --- Rings, bars and pills (small bits of HTML) ---

_CSS = """<style>
.vk-rings { display: flex; flex-wrap: wrap; gap: 18px 26px; align-items: center; justify-content: space-around; }
.vk-ring { display: flex; flex-direction: column; align-items: center; gap: 4px; min-width: 84px; }
.vk-dial { border-radius: 50%; }
.vk-dial-mid { display: flex; flex-direction: column; align-items: center; justify-content: center; line-height: 1.1;
               font-variant-numeric: tabular-nums; }
.vk-dial-mid span { opacity: 0.65; }
.vk-ring .t { font-size: 0.8rem; opacity: 0.75; text-align: center; }
.vk-ring .s { font-size: 0.78rem; opacity: 0.65; text-align: center; font-variant-numeric: tabular-nums; }
.vk-bars { display: grid; gap: 9px; }
.vk-bar { display: grid; grid-template-columns: minmax(5.5em, auto) 1fr auto; align-items: center; gap: 10px;
          font-size: 0.88rem; }
.vk-bar .track { height: 8px; border-radius: 999px; background: rgba(128,128,128,.18); overflow: hidden; }
.vk-bar .track i { display: block; height: 100%; border-radius: 999px; }
.vk-bar .v { text-align: right; font-variant-numeric: tabular-nums; opacity: 0.85; }
.vk-pills { display: flex; flex-wrap: wrap; gap: 6px; }
.vk-pill { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 0.78rem; font-weight: 600;
           line-height: 1.5; white-space: nowrap; }
.vk-date { display: inline-flex; flex-direction: column; align-items: center; justify-content: center;
           width: 3.1rem; height: 3.3rem; border-radius: 10px; border: 1px solid rgba(128,128,128,.25);
           line-height: 1.05; }
.vk-date b { font-size: 1.25rem; } .vk-date span { font-size: 0.68rem; text-transform: uppercase; opacity: .7;
           letter-spacing: .06em; }
</style>"""


def _css():
    st.html(_CSS)


def ring_html(frac, colour, size=84, width=9, centre="", sub=""):
    """A progress ring in plain HTML/CSS (st.html drops SVG): a conic gradient with a hole cut out."""
    frac = max(0.0, min(1.0, frac or 0))
    hole = size / 2 - width
    return (f'<div class="vk-dial" style="width:{size}px;height:{size}px;'
            f'background:conic-gradient({colour} {frac * 360:.1f}deg, {TRACK} 0);'
            f'-webkit-mask:radial-gradient(circle, transparent {hole - 0.5}px, #000 {hole}px);'
            f'mask:radial-gradient(circle, transparent {hole - 0.5}px, #000 {hole}px)"></div>'
            f'<div class="vk-dial-mid" style="width:{size}px;height:{size}px;margin-top:-{size}px">'
            f'<b style="font-size:{size * 0.2:.0f}px">{escape(centre)}</b>'
            + (f'<span style="font-size:{max(11, size * 0.11):.0f}px">{escape(sub)}</span>' if sub else "")
            + "</div>")


def rings(items, size=84):
    """A row of progress rings. items: dicts with frac (0..1), colour, centre, title, sub, and optionally
    size and centre_sub (small text under the centre number)."""
    _css()
    html = "".join(
        f'<div class="vk-ring">{ring_html(i["frac"], i["colour"], i.get("size", size), max(7, i.get("size", size) // 10), i.get("centre", ""), i.get("centre_sub", ""))}'
        f'<div class="t">{escape(i.get("title", ""))}</div>'
        + (f'<div class="s">{escape(i["sub"])}</div>' if i.get("sub") else "") + "</div>" for i in items)
    st.html(f'<div class="vk-rings">{html}</div>')


def bars(items):
    """Labelled horizontal progress bars. items: dicts with label, frac (0..1), colour, value (text on the right)."""
    _css()
    html = "".join(
        (f'<div class="vk-bar"><span>{escape(i["label"])}</span>' if i["label"] else
         '<div class="vk-bar" style="grid-template-columns:1fr auto">')
        + f'<span class="track">'
        f'<i style="width:{100 * max(0, min(1, i["frac"] or 0)):.0f}%;background:{i["colour"]}"></i></span>'
        f'<span class="v">{escape(i.get("value", ""))}</span></div>' for i in items)
    st.html(f'<div class="vk-bars">{html}</div>')


def pill(text, colour):
    """A soft pill: tinted background, the colour as text. Returns HTML (for use inside pills_html)."""
    return (f'<span class="vk-pill" style="background:{rgba(colour, 0.14)};'
            f'color:color-mix(in srgb, {colour} 55%, currentColor);'
            f'border:1px solid {rgba(colour, 0.35)}">{escape(text)}</span>')


def pills(items):
    """A row of pills. items: (text, colour) pairs."""
    _css()
    if items:
        st.html('<div class="vk-pills">' + "".join(pill(t, c) for t, c in items) + "</div>")


def date_badge(day):
    """A small calendar-page badge (HTML) for a date."""
    return f'<span class="vk-date"><b>{day.day}</b><span>{day:%b}</span></span>'


def html(markup):
    _css()
    st.html(markup)
