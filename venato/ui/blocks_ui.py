"""
Choosing blocks: cards to tick, grouped (setup wizard and Settings → Blocks), and the order
of the ones switched on, which is the order of their widgets on Home.
"""

import streamlit as st

from venato import blocks

COLUMNS = 3


def _toggle(key, widget):
    keys = blocks.chosen_keys()
    if st.session_state[widget] and key not in keys:
        keys.append(key)
    elif not st.session_state[widget]:
        keys = [k for k in keys if k != key]
    blocks.save(keys)


def _move(key, step):
    keys = blocks.chosen_keys()
    i = keys.index(key)
    j = max(0, min(len(keys) - 1, i + step))
    keys[i], keys[j] = keys[j], keys[i]
    blocks.save(keys)


def picker(prefix):
    """Cards for every block, grouped, each with a switch."""
    on = set(blocks.chosen_keys())
    st.html("""<style>
      .bk-name { font-weight: 650; font-size: 1rem; }
      .bk-blurb { font-size: 0.82rem; opacity: 0.8; line-height: 1.35; min-height: 2.7em; }
    </style>""")
    for group in blocks.GROUPS:
        members = [b for b in blocks.all_blocks() if b.group == group]
        if not members:
            continue
        st.markdown(f"**{group}**")
        cols = st.columns(COLUMNS)
        for i, b in enumerate(members):
            with cols[i % COLUMNS].container(border=True):
                st.html(f'<div class="bk-name">{b.name}</div><div class="bk-blurb">{b.blurb}</div>')
                widget = f"{prefix}_block_{b.key}"
                st.toggle(f"{b.icon} Use {b.name}", value=b.key in on, key=widget, disabled=b.core,
                          on_change=_toggle, args=(b.key, widget), label_visibility="visible")


def priorities(prefix):
    """The switched-on blocks in order, with up / down: Home shows their widgets in this order."""
    keys = blocks.chosen_keys()
    if not keys:
        st.caption("No blocks switched on yet.")
        return
    for i, key in enumerate(keys):
        b = blocks.get(key)
        name, up, down = st.columns([6, 1, 1], vertical_alignment="center")
        name.markdown(f"{i + 1}. {b.icon} **{b.name}**" + ("" if b.home else "  \n:gray[(no Home widget)]"))
        up.button("", icon=":material/arrow_upward:", key=f"{prefix}_up_{key}", disabled=i == 0,
                  on_click=_move, args=(key, -1), help=f"Move {b.name} up")
        down.button("", icon=":material/arrow_downward:", key=f"{prefix}_down_{key}", disabled=i == len(keys) - 1,
                    on_click=_move, args=(key, 1), help=f"Move {b.name} down")


def section(prefix):
    st.markdown("Venato is made of **blocks**. Switch on the ones you want: each adds a page "
                "(and a widget on Home). You can change this any time.")
    picker(prefix)
    st.subheader("Your priorities", anchor=False)
    st.caption("Home shows the widgets of your blocks in this order: put what matters most first.")
    priorities(prefix)
