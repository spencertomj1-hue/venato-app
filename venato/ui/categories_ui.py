"""
Under the timetable: "Categories and rules". Change a category's name or colour,
add or delete categories, and set rules like "anything containing Gym is Sport".
store.py keeps them; the grid and Outlook events use them straight away.
"""

import streamlit as st

from venato import store


def _text_colour(cat):
    return cat["text_colour"] if isinstance(cat["text_colour"], str) else None


def _rename(cat, key, others):
    name = st.session_state[key].strip()
    if not name or name == cat["name"]:
        return
    if name.lower() in others:
        st.toast(f"There's already a category called '{name}'.", icon=":material/error:")
        return
    store.save_category(cat["id"], name, cat["colour"], cat["grp"], _text_colour(cat))


def _recolour(cat, key):
    store.save_category(cat["id"], cat["name"], st.session_state[key], cat["grp"], _text_colour(cat))


def _delete(cat, cats):
    """A category's events have to go somewhere, so deleting moves them to another one first."""
    others = {c["name"]: c["id"] for c in cats if c["id"] != cat["id"]}
    blocks, _ = store.category_usage(cat["id"])
    st.write(f"**{cat['name']}** is used by {blocks} event{'s' * (blocks != 1)}.")
    target = st.selectbox("Move them to", list(others), key=f"cat_to_{cat['id']}")
    if st.button("Delete category", key=f"cat_del_{cat['id']}", type="primary", width="stretch"):
        store.merge_categories(cat["id"], others[target])
        st.rerun()


def _categories():
    cats = store.load_categories().to_dict("records")
    for cat in cats:
        colour, name, delete = st.columns([1, 8, 2], vertical_alignment="center")
        key = f"cat_col_{cat['id']}"
        st.session_state[key] = cat["colour"]          # always what's saved (Claude can change it too)
        colour.color_picker("Colour", key=key, label_visibility="collapsed", on_change=_recolour, args=(cat, key))
        key = f"cat_name_{cat['id']}"
        st.session_state[key] = cat["name"]
        others = {c["name"].lower() for c in cats if c["id"] != cat["id"]}
        name.text_input("Name", key=key, label_visibility="collapsed", on_change=_rename, args=(cat, key, others))
        if len(cats) > 1:
            with delete.popover("Delete", icon=":material/delete:", width="stretch"):
                _delete(cat, cats)

    with st.form("cat_add", clear_on_submit=True, border=False):
        colour, name, add = st.columns([1, 8, 2], vertical_alignment="bottom")
        new_colour = colour.color_picker("Colour", value="#3E8EF7", label_visibility="collapsed")
        new_name = name.text_input("New category", placeholder="New category", label_visibility="collapsed")
        if add.form_submit_button("Add", icon=":material/add:", width="stretch"):
            try:
                store.add_category(new_name, new_colour)
                st.rerun()
            except ValueError as e:
                st.error(str(e))


def _rules():
    st.markdown("**Rules**")
    st.caption("An event with this word in its name goes straight into that category, including Outlook events "
               "and new events as you type them.")
    cats = store.load_categories().to_dict("records")
    ids = {c["name"]: c["id"] for c in cats}
    names = {c["id"]: c["name"] for c in cats}
    for rule in store.load_rules():
        text, remove = st.columns([9, 2], vertical_alignment="center")
        text.markdown(f"**{rule['word']}** → {names.get(rule['category_id'], 'Deleted category')}")
        if remove.button("Remove", key=f"rule_del_{rule['id']}", icon=":material/close:", width="stretch"):
            store.delete_rule(rule["id"])
            st.rerun()

    with st.form("rule_add", clear_on_submit=True, border=False):
        word, category = st.columns(2)
        new_word = word.text_input("If an event contains", placeholder="e.g. Gym")
        new_category = category.selectbox("Put it in", list(ids))
        existing = st.checkbox("Also change events already on the timetable", value=True)
        if st.form_submit_button("Add rule", icon=":material/add:"):
            try:
                changed = store.add_rule(new_word, ids[new_category], existing)
                st.toast(f"Rule added. {changed} event{'s' * (changed != 1)} changed.", icon=":material/check_circle:")
                st.rerun()
            except ValueError as e:
                st.error(str(e))


def render():
    with st.expander("Categories and rules", icon=":material/palette:"):
        _categories()
        st.divider()
        _rules()
