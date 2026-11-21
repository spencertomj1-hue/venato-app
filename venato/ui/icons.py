"""
Venato's own glyphs for the built-in blocks, drawn over the Material icon Streamlit puts in a button.

st.button only takes emoji or :material/x: icons, so the block keeps its Material icon (search, Settings and
anything else still show that) and CSS paints our glyph on top: the Material glyph goes transparent and a
::after with the SVG as a mask shows through in white. One 24px stroke grid, round caps and joins.
"""

from urllib.parse import quote

_PATHS = {
    ":material/calendar_view_week:":    # Timetable: a week with slots
        '<rect x="3" y="5" width="18" height="16" rx="2.5"/><path d="M3 10h18M8 3v4M16 3v4M7.5 14h3M13.5 14h3M7.5 17.5h3"/>',
    ":material/flag:":                  # Goals
        '<path d="M5 21V3.5M5 4h12.5l-2.75 4.25L17.5 12.5H5"/>',
    ":material/timer:":                 # Focus: a stopwatch
        '<circle cx="12" cy="13.5" r="7.5"/><path d="M12 13.5V9.5M10 2.5h4M12 2.5V6M18.5 7l1.5-1.5"/>',
    ":material/school:":                # Modules: a mortarboard
        '<path d="M2.5 9.5 12 5l9.5 4.5L12 14z"/><path d="M6.5 11.5V16c0 1.4 2.5 3 5.5 3s5.5-1.6 5.5-3v-4.5M21.5 9.5v5"/>',
    ":material/monitoring:":            # Review: a rising line
        '<path d="M4 4v16h16M7.5 15.5l3.5-4 3 2.5 5-6.5"/>',
    ":material/edit_calendar:":         # Daily Log: the journal book
        '<path d="M12 6.5C10 5 7 4.5 3.5 4.5v14c3.5 0 6.5.5 8.5 2 2-1.5 5-2 8.5-2v-14C17 4.5 14 5 12 6.5zM12 6.5v14"/>',
}


def svg(icon):
    """The glyph for a Material icon string as a standalone SVG, or "" when it has none of ours."""
    paths = _PATHS.get(icon)
    if not paths:
        return ""
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#000" '
            f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{paths}</svg>')


def name(icon):
    """A CSS class naming our glyph for `icon` (drawn by classes_css), or "" when it has none."""
    return f"vn-g-{icon.strip(':').split('/')[-1]}" if icon in _PATHS else ""


def classes_css():
    """Every glyph as a class for spans drawn in markdown (nav.icon_md): `<span class="vn-g-flag">`."""
    return "".join(_rule(f".{name(i)}", i) for i in _PATHS)


def _rule(sel, icon, inset="18%"):
    """`sel` (one or more comma-joined selectors) drawn as our glyph for `icon`, in white."""
    url = f'url("data:image/svg+xml,{quote(svg(icon))}")'
    after = ", ".join(f"{x}::after" for x in sel.split(", "))
    return (f"{sel} {{ position: relative; -webkit-text-fill-color: transparent !important; }}"
            f"{after} {{ content: ''; position: absolute; inset: {inset}; background: #fff;"
            f" -webkit-mask: {url} center / contain no-repeat; mask: {url} center / contain no-repeat; }}")


def css(selectors, icon, inset="18%"):
    """CSS that paints our glyph for `icon` over the Material icon inside each of `selectors` (CSS selectors
    of the icon's container), or "" when `icon` has no glyph of ours."""
    if icon not in _PATHS:
        return ""
    return _rule(", ".join(f"{x} [data-testid='stIconMaterial']" for x in selectors), icon, inset)
