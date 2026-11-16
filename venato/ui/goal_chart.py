"""
The Goals page's pace chart (inline SVG, no libraries): for one goal, its progress so far (solid accent),
an even pace from 0 to the target (dashed grey), where it ends up at the recent rate (dotted accent) and a
"today" line. legend() is drawn once at the top of the page; the chart itself only labels the target and
today's value. Each chart is role="img" with an aria-label that says the numbers.
"""

from html import escape
from urllib.parse import quote

from venato import pace
from venato import regional

W, H = 300, 112          # drawing area (the SVG scales to its card)
PAD_T, PAD_R, PAD_B, PAD_L = 14, 34, 6, 4


def colours():
    """(accent, grey, text, page) for the current theme: lines 3:1+ and text 4.5:1+ on the page."""
    from venato.ui import appearance
    dark = appearance.is_dark()
    return (appearance.accent(), "#A3A8B8" if dark else "#5F6170", "#FAFAFA" if dark else "#31333F",
            "#0E1117" if dark else "#FFFFFF")


def legend():
    """One legend for every chart on the page (identity is never colour alone: solid / dashed / dotted)."""
    accent, grey, _, _ = colours()

    def key(style, text):
        return f'<span class="gc-k"><i style="{style}"></i>{text}</span>'
    return f"""<style>
      .gc-legend {{ display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: 0.82rem; }}
      .gc-k {{ display: inline-flex; align-items: center; gap: 6px; }}
      .gc-k i {{ display: inline-block; width: 24px; height: 0; }}
      .gc img {{ display: block; width: 100%; height: auto; }}
    </style><div class="gc-legend" aria-hidden="true">
      {key(f"border-top: 2px solid {accent}", "Actual")}{key(f"border-top: 2px dashed {grey}", "Even pace")}
      {key(f"border-top: 3px dotted {accent}", "At this rate")}
      {key(f"width: 0; height: 12px; border-left: 1.5px solid {grey}", "Today")}
    </div>"""


def chart(p, ctx):
    """The SVG for one goal's pace (p: pace.goal_pace), or "" for goals that haven't started."""
    g = p["goal"]
    if p["state"] == "upcoming":
        return ""
    accent, grey, ink, page = colours()
    start, end, today = p["start"], p["end"], min(ctx.today, p["end"])
    days = (end - start).days + 1
    target, value = p["target"], p["value"]
    hist = pace.history(g, ctx)
    rate = (p["rate"] or 0) / 7                                  # per day
    left = (end - today).days                                    # whole days after today
    proj_end = value + rate * left if p["rate"] and p["state"] not in ("done", "ended") else None
    top = max(target, value, proj_end or 0) * 1.08 or 1
    x = lambda d: PAD_L + (W - PAD_L - PAD_R) * ((d - start).days + 1) / days
    y = lambda v: PAD_T + (H - PAD_T - PAD_B) * (1 - v / top)
    base = y(0)

    parts = [f'<line x1="{PAD_L}" y1="{base:.1f}" x2="{W - PAD_R}" y2="{base:.1f}" stroke="{grey}" stroke-opacity="0.45"/>',
             f'<line x1="{PAD_L}" y1="{base:.1f}" x2="{x(end):.1f}" y2="{y(target):.1f}" stroke="{grey}" stroke-width="2" '
             f'stroke-dasharray="5 4"><title>Even pace to {escape(pace.amount(g, target))}</title></line>',
             f'<text x="{x(end) + 4:.1f}" y="{y(target) + 4:.1f}" font-weight="400">{escape(pace.fmt(target))}</text>']
    if hist:
        step = 1 if days <= 62 else 7                            # a year: a point a week
        pts = [pt for i, pt in enumerate(hist) if i % step == 0 or i == len(hist) - 1]
        line = " ".join(f"{x(d):.1f},{y(v):.1f}" for d, v in pts)
        parts.append(f'<polyline points="{line}" fill="none" stroke="{accent}" stroke-width="2" stroke-linejoin="round" '
                     f'stroke-linecap="round"><title>{escape(pace.amount(g, value))} so far</title></polyline>')
    if proj_end is not None and left > 0:
        if p["finish"] and p["finish"] <= end:
            fx, fy = x(p["finish"]), y(target)
        else:
            fx, fy = x(end), y(proj_end)
        parts.append(f'<line x1="{x(today):.1f}" y1="{y(value):.1f}" x2="{fx:.1f}" y2="{fy:.1f}" stroke="{accent}" '
                     f'stroke-width="2" stroke-dasharray="1 4" stroke-linecap="round"><title>At this rate</title></line>')
    if ctx.today <= end:
        parts.append(f'<line x1="{x(today):.1f}" y1="{PAD_T - 6}" x2="{x(today):.1f}" y2="{base:.1f}" stroke="{grey}" '
                     f'stroke-width="1.5" stroke-opacity="0.8"/>')
    parts.append(f'<circle cx="{x(today):.1f}" cy="{y(value):.1f}" r="4.5" fill="{accent}" stroke="{page}" '
                 f'stroke-width="2"><title>{escape(pace.amount(g, value))} by {regional.day_month(today)}</title></circle>')
    parts.append(f'<text x="{min(x(today) + 7, W - PAD_R - 20):.1f}" y="{max(y(value) - 7, 10):.1f}">{escape(pace.fmt(value))}</text>')
    # An <img> of the SVG (st.html strips inline SVG); its alt text says the numbers.
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="system-ui, sans-serif" '
           f'font-size="10.5" font-weight="600" fill="{ink}">{"".join(parts)}</svg>')
    return (f'<div class="gc"><img role="img" src="data:image/svg+xml;charset=utf-8,{quote(svg)}" '
            f'alt="{escape(describe(p, ctx))}"></div>')


def describe(p, ctx):
    """The chart in words: where it is, where an even pace would be, and where the recent rate takes it."""
    g = p["goal"]
    today = min(ctx.today, p["end"])
    text = f"{g['title']}: {pace.amount(g, p['value'])} of {pace.amount(g, p['target'])} by {regional.day_month(today)}"
    if p["state"] in ("done", "ended"):
        return text + "."
    text += f", against {pace.amount(g, round(p['expected'], 1))} on an even pace"
    if p["finish"] and p["late"] is not None:
        when = "on the last day" if p["late"] == 0 else (f"{p['late']} days late" if p["late"] > 0 else f"{-p['late']} days early")
        text += f"; at this rate it reaches {pace.amount(g, p['target'])} {when}"
    elif p["rate"] is not None and g["kind"] != "count":
        text += "; no progress in the last 4 weeks to project from"
    if g["kind"] == "hours" and p.get("week"):
        w = p["week"]
        text += f". Based on {w['confirmed_days']} of {w['days_so_far']} confirmed days this week"
    return text + "."


def week_line(p):
    """Hours goals: this week's own numbers ("This week 6 / 12 h · 4.5 h short"), or ""."""
    w = p.get("week")
    if not w or p["state"] in ("done", "ended", "upcoming"):
        return ""
    f = pace.fmt
    text = f"This week {f(w['done'] + w['planned_future'] + w.get('assumed', 0))} / {f(w['want'])} h done or planned"
    if w["short"] >= pace.TOLERANCE:
        text += f" · {f(w['short'])} h short"
    if w["days_so_far"]:
        text += f" · done from {w['confirmed_days']} of {w['days_so_far']} confirmed days"
    return text
