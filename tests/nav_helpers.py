"""Getting round the app in AppTest now there's no sidebar: the router is session_state["page"] (venato/ui/nav.py)."""


def goto(at, page):
    """Open a page the way a tile or shortcut does, and draw it."""
    at.session_state["page"] = page
    return at.run()


def page_names():
    """Home, the switched-on blocks' pages, Settings (what the shortcut tiles offer)."""
    from venato.ui import nav
    return list(nav.pages())
