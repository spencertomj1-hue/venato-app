"""
The "Paper" look: serif headings (Fraunces, bundled in assets/fonts) in both modes, and in
light mode a warm paper background and white buttons with a warm border.

Dark mode keeps its own colours; only the fonts change there. The timetable's own header reads --venato-serif (see
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
BORDER = "#D9D4C8"         # button borders
INK = "#1F1E1C"
RED = "#B42318"

def _fonts():
    """Both modes: the serif for headings, card titles, metric numbers and the timetable's header."""
    return f"""
    {_FACES}
    :root {{ --venato-serif: {SERIF}; }}
    .stApp h1, .stApp h2, .stApp h3, .stApp h4,
    .stApp h1 *, .stApp h2 *, .stApp h3 *, .stApp h4 * {{
        font-family: {SERIF} !important; font-weight: 600 !important; letter-spacing: -0.005em; }}
    [data-testid="stMetricValue"], [data-testid="stMetricValue"] * {{ font-family: {SERIF} !important; }}
    /* Card titles and subheadings: text made with kit.subhead (kit.card, "Needs you"...). */
    .stApp .vn-subhead, .stApp .vn-subhead strong {{
        font-family: {SERIF}; font-size: 1.19rem; font-weight: 600; }}
    """


def _light():
    """Light mode only: paper background, Paper's buttons."""
    return f"""
    .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"], [data-testid="stMain"],
    [data-testid="stBottom"] > div, [data-testid="stBottomBlockContainer"] {{ background: {PAPER} !important; }}

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
