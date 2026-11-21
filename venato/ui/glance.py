"""
Small fixed-height graphics for Home's tiles: a row of day dots and a coloured pill. Each says the same in
words (an aria-label, or the pill's own text), works light and dark, and never grows its tile.
"""

from html import escape

from venato.ui import appearance

TONES = {"red": "red", "amber": "orange", "grey": "gray"}      # pill tones -> Streamlit's badge colours


def dots(flags, label, letters=None):
    """A row of small dots, filled where flags is true (e.g. the week's days written). letters: one under each.
    Returns HTML for st.html; label is what a screen reader hears ("Written 3 of 7 days this week")."""
    t = appearance.tokens()
    cells = "".join(
        f'<span><i class="{"on" if f else ""}"></i>{f"<b>{escape(letters[i])}</b>" if letters else ""}</span>'
        for i, f in enumerate(flags))
    return (f"""<style>
      .vn-dots {{ display: flex; gap: 8px; height: {30 if letters else 14}px; align-items: flex-start; }}
      .vn-dots span {{ display: flex; flex-direction: column; align-items: center; gap: 2px; width: 14px; }}
      .vn-dots i {{ width: 12px; height: 12px; border-radius: 50%; box-sizing: border-box;
        border: 1.5px solid {t['muted']}; opacity: 0.55; }}
      .vn-dots i.on {{ background: {t['accent']}; border-color: {t['accent']}; opacity: 1; }}
      .vn-dots b {{ font-size: 0.62rem; font-weight: 500; color: {t['muted']}; line-height: 1; }}
    </style><div class="vn-dots" role="img" aria-label="{escape(label)}">{cells}</div>""")


def pill(text, tone):
    """A small coloured pill (Streamlit markdown, so it works inside a button's label too): tone is "red",
    "amber" or "grey"."""
    return f":{TONES.get(tone, 'gray')}-badge[{str(text).replace(']', '')}]"
