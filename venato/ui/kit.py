"""
Shared look for the block pages: cards, stat tiles, charts, tables, progress rings and pills,
so Money, Workouts and Grades all read as one app.

Everything is built from Streamlit's own pieces (bordered containers, st.metric, st.dataframe,
Altair) plus a little HTML for rings and pills, and works in light and dark mode.
"""

import functools
from contextlib import contextmanager
from html import escape

import altair as alt
import pandas as pd
import streamlit as st

from venato import store
from venato.ui import appearance

# One colour per category, the same on every chart: Tableau 10 without its red, which means
# "over" / "bad" here. Distinct, and readable on light and dark backgrounds.
PALETTE = ["#4E79A7", "#F28E2B", "#59A14F", "#8CD17D", "#76B7B2", "#EDC948", "#B07AA1", "#FF9DA7", "#9C755F",
           "#BAB0AC"]
# The same ten on the paper-coloured light background, darkened so each is 3:1 or more against it (WCAG
# non-text contrast); the dark-mode set above is already well over that on the dark background.
PALETTE_LIGHT = ["#4E79A7", "#C96A00", "#3F8A3B", "#5F9C16", "#2A9A92", "#A88400", "#B07AA1", "#D9607A", "#8B6B4F",
                 "#7C8590"]
DAY_FORMAT = "%-d %b"      # '5 Nov' for chart dates: a d3 format drawn in the browser, fine on Windows too
GRID = "rgba(128,128,128,0.15)"
TRACK = "rgba(128,128,128,0.18)"


def colours(names):
    """{name: colour}, stable for a given order of names."""
    palette = PALETTE if appearance.is_dark() else PALETTE_LIGHT
    return {n: palette[i % len(palette)] for i, n in enumerate(names)}


def muted():
    """A quiet grey for 'planned' / 'last week' series, readable on the current background."""
    return "#9AA0AE" if appearance.is_dark() else "#6F7685"


def water():
    return "#3E8EF7" if appearance.is_dark() else "#1F6FD6"


def ink():
    """Text colour for chart labels drawn as marks (Streamlit's theme only colours axes and legends)."""
    return "#E8E8EC" if appearance.is_dark() else "#262730"


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


# --- Charts (Altair, which ships with Streamlit) ---

def colour_scale(names, palette=None):
    """An Altair colour scale, one app colour per category. palette: {name: colour}, else kit.colours order."""
    names = list(dict.fromkeys(names))
    cmap = palette or colours(names)
    return alt.Scale(domain=names, range=[cmap.get(n, PALETTE[-1]) for n in names])


def _long(df, x, y):
    """Wide to long when y is a list of columns: (df, y column, series column)."""
    if isinstance(y, (list, tuple)):
        return df.melt(id_vars=[x], value_vars=list(y), var_name="Series", value_name="Value"), "Value", "Series"
    return df, y, None


def _kind(df, col):
    return "temporal" if pd.api.types.is_datetime64_any_dtype(df[col]) else \
        "quantitative" if pd.api.types.is_numeric_dtype(df[col]) else "nominal"


def style(chart, height, legend, legend_columns=4):
    """The app's chart style: tight, quiet gridlines, no frame, legend underneath only when asked for."""
    return (chart.properties(height=height, padding={"left": 0, "right": 8, "top": 8, "bottom": 4})
            .configure_view(stroke=None)
            .configure_axis(gridColor=GRID, domain=False, ticks=False, title=None, labelPadding=6)
            .configure_legend(orient="bottom", title=None, disable=not legend, labelLimit=240, columns=legend_columns, symbolType="circle")
            .configure_title(anchor="start", fontSize=14))


def line_chart(df, x, y, color=None, y_title=None, height=260, *, palette=None, points=True, x_axis=None,
               x_scale=None, y_scale=None, y_axis=None, title=None, colour=None):
    """Lines over time. y: a column, or a list of columns drawn as one line each (named by the columns).
    color: a column that splits the lines. palette: {series: colour}. x_axis / x_scale / y_scale / y_axis:
    alt.Axis / alt.Scale overrides. Returns an Altair chart; draw it with show()."""
    df, y, series = _long(df, x, y)
    color = color or series
    enc = dict(x=alt.X(x, type=_kind(df, x), scale=x_scale or alt.Scale(),
                       axis=x_axis or alt.Axis(labelOverlap=True)),
               y=alt.Y(y, type="quantitative", scale=y_scale or alt.Scale(zero=False),
                       axis=y_axis or alt.Axis(title=y_title)))
    if color:
        enc["color"] = alt.Color(color, type="nominal", scale=colour_scale(df[color], palette))
        enc["tooltip"] = [x, color, y]
    else:
        enc["tooltip"] = [x, y]
    base = alt.Chart(df, title=title or "")
    line = base.mark_line(point=alt.OverlayMarkDef(filled=True, size=45) if points else False,
                          strokeWidth=2.5).encode(**enc)
    if not color:
        line = line.encode(color=alt.value(colour or colours([0])[0]))
    return style(line, height, legend=bool(color))


def bar_chart(df, x, y, color=None, stack=False, horizontal=False, height=260, *, palette=None, x_axis=None,
              x_scale=None, y_scale=None, y_axis=None, title=None, labels=None, size=None, colour=None):
    """Bars. color: a column that splits the bars, stacked when stack=True, side by side otherwise.
    horizontal swaps the axes (x stays the category, y the value). labels: a number format ('.1f') to print
    values on the bars. Returns an Altair chart; draw it with show()."""
    cat_kind = _kind(df, x)
    cat = alt.X(x, type=cat_kind, scale=x_scale or alt.Scale(),
                axis=x_axis or alt.Axis(labelAngle=0, labelLimit=110, grid=False))
    val = alt.Y(y, type="quantitative", scale=y_scale or alt.Scale(zero=True), axis=y_axis or alt.Axis())
    enc = dict(x=cat, y=val, tooltip=[x, y] if not color else [x, color, y])
    if horizontal:
        enc["x"], enc["y"] = alt.X(y, type="quantitative", scale=y_scale or alt.Scale(zero=True),
                                   axis=y_axis or alt.Axis()), alt.Y(x, type=cat_kind, axis=x_axis or alt.Axis(),
                                                                     sort=None)
    if color:
        enc["color"] = alt.Color(color, type="nominal", scale=colour_scale(df[color], palette))
        if not stack and not horizontal:
            enc["xOffset"] = alt.XOffset(color, type="nominal")
        if not stack and horizontal:
            enc["yOffset"] = alt.YOffset(color, type="nominal")
    else:
        enc["color"] = alt.value(colour or colours([0])[0])
    mark = alt.Chart(df, title=title or "").mark_bar(**({"size": size} if size else {}))
    chart = mark.encode(**enc)
    if labels:
        text = alt.Chart(df).mark_text(dy=-6 if not horizontal else 0, dx=12 if horizontal else 0, fontSize=11,
                                           color=ink())
        t_enc = {k: v for k, v in enc.items() if k in ("x", "y", "xOffset", "yOffset")}
        chart = chart + text.encode(text=alt.Text(y, type="quantitative", format=labels), **t_enc)
    return style(chart, height, legend=bool(color))


def show(chart, key=None):
    """Draw an Altair chart with Streamlit's own theme (light or dark, fonts, text colours)."""
    st.altair_chart(chart, width="stretch", theme="streamlit", key=key)


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


def _cache_key():
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
        return remembered(_cache_key(), *args, **kwargs)
    return wrapper
