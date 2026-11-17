"""
The "Paper" look: serif headings (Fraunces, bundled in assets/fonts) in both modes, and in
light mode a warm paper background, a plain paper sidebar with the Venato mark, and
white buttons with a warm border.

Dark mode keeps its own colours and the marble sidebar (sidebar_theme.py); only the
fonts change there. The timetable's own header reads --venato-serif (see
components/timetable_component.css), which reaches inside the component.
"""

import base64
from pathlib import Path

import streamlit as st

_FONTS = Path(__file__).parents[2] / "assets" / "fonts"
_FACES = "".join(
    f"@font-face {{ font-family: 'Fraunces'; font-style: normal; font-weight: {w}; font-display: swap;"
    f" src: url(data:font/woff2;base64,{base64.b64encode((_FONTS / f'Fraunces-{w}.woff2').read_bytes()).decode()})"
    f" format('woff2'); }}\n"
    for w in (500, 600))

SERIF = "Fraunces, Georgia, 'Times New Roman', serif"
PAPER = "#F6F4EF"          # the page
EDGE = "#E4E0D6"           # hairlines (sidebar edge)
BORDER = "#D9D4C8"         # button borders
INK = "#1F1E1C"
NAV = "#3A3833"
HOVER = "#ECE8DF"
RED = "#B42318"

_MARK = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='30' height='30'%3E"
         "%3Crect width='30' height='30' rx='8' fill='%231F1E1C'/%3E%3Ctext x='15' y='21' "
         "font-family='Georgia,serif' font-size='17' font-weight='600' fill='%23F6F4EF' "
         "text-anchor='middle'%3EV%3C/text%3E%3C/svg%3E")


def _fonts():
    """Both modes: the serif for headings, card titles, metric numbers and the timetable's header."""
    return f"""
    {_FACES}
    :root {{ --venato-serif: {SERIF}; }}
    .stApp h1, .stApp h2, .stApp h3, .stApp h4,
    .stApp h1 *, .stApp h2 *, .stApp h3 *, .stApp h4 * {{
        font-family: {SERIF} !important; font-weight: 600 !important; letter-spacing: -0.005em; }}
    [data-testid="stMetricValue"], [data-testid="stMetricValue"] * {{ font-family: {SERIF} !important; }}
    /* Card titles are a paragraph that's just one bold phrase (kit.card, "Needs you this week"...). */
    .stApp [data-testid="stMarkdownContainer"] > p:only-child > strong:first-child:last-child {{
        font-family: {SERIF}; font-size: 1.19rem; font-weight: 600; }}
    """


def _light():
    """Light mode only: paper background, paper sidebar, Paper's buttons."""
    return f"""
    .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"], [data-testid="stMain"],
    [data-testid="stBottom"] > div, [data-testid="stBottomBlockContainer"] {{ background: {PAPER} !important; }}

    /* Sidebar: plain paper with a hairline edge (instead of the marble), the mark and name at the top. */
    [data-testid="stSidebar"] {{ background: {PAPER} !important; border-right: 1px solid {EDGE} !important; }}
    [data-testid="stSidebar"][data-collapsed="false"] {{
        width: 11.5rem !important; min-width: 11.5rem !important; max-width: 11.5rem !important; }}
    [data-testid="stSidebarHeader"] {{ position: absolute; top: 0; right: 0.25rem; z-index: 2; }}
    [data-testid="stSidebar"] [data-testid="stElementContainer"]:has(h1) {{ display: block !important; }}
    [data-testid="stSidebar"] h1 {{
        display: block !important; margin: 0.6rem 0 1.4rem; padding: 0 0 0 40px !important;
        background: no-repeat 0 50% / 30px 30px url("{_MARK}");
        font-family: {SERIF} !important; font-size: 1.4rem !important; font-weight: 600 !important;
        line-height: 2.2rem !important; color: {INK} !important; }}
    [data-testid="stSidebar"] h1 a {{ display: none !important; }}
    [data-testid="stSidebar"] [data-testid="stRadioGroup"] {{ gap: 2px !important; }}
    [data-testid="stSidebar"] [data-testid="stRadioOption"],
    [data-testid="stSidebar"] [data-testid="stRadioOption"]:hover,
    [data-testid="stSidebar"] [data-testid="stRadioOption"][data-selected="true"] {{ padding: 0 !important; }}
    [data-testid="stSidebar"] [data-testid="stRadioOption"] p {{
        display: block !important; background: transparent !important; box-shadow: none !important;
        padding: 9px 14px !important; border-radius: 10px !important;
        font-size: 0.95rem !important; font-weight: 500 !important; color: {NAV} !important; }}
    [data-testid="stSidebar"] [data-testid="stRadioOption"]:hover p {{ background: {HOVER} !important; color: {INK} !important; }}
    [data-testid="stSidebar"] [data-testid="stRadioOption"][data-selected="true"] p {{
        background: #FFFFFF !important; box-shadow: 0 1px 0 {EDGE} !important;
        color: {RED} !important; font-weight: 700 !important; }}

    /* Buttons: white with a warm border, squarer corners; the red ones in Paper's red. */
    .stApp [data-testid^="stBaseButton-secondary"] {{
        background: #FFFFFF !important; border: 1px solid {BORDER} !important;
        border-radius: 10px !important; color: {INK} !important; font-weight: 600 !important; }}
    .stApp [data-testid^="stBaseButton-secondary"]:hover {{ background: #F3F0E9 !important; }}
    .stApp [data-testid^="stBaseButton-primary"] {{
        background: {RED} !important; border-color: {RED} !important; border-radius: 10px !important; }}
    .stApp [data-testid^="stBaseButton-tertiary"] p {{ font-weight: 600; }}
    """


def apply():
    from venato.ui import appearance
    st.html(f"<style>{_fonts()}{'' if appearance.is_dark() else _light()}</style>")
