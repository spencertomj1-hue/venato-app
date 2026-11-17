"""
AppTest helpers for st.fragment (also used by scripts/profile_pages.py).

AppTest's own `.run()` always reruns the whole app, but in the browser a widget inside a fragment
reruns only that fragment (its callbacks still run first). `interact` runs an interaction the way
the browser does: just the widget's fragment when it's in one, else the whole app. It also fires
a custom component's trigger (st.components.v2), which AppTest can't click.

    with fragment_run.recording():               # notes which fragment each element is drawn in
        at = AppTest.from_file(APP).run()
        fragment_run.trigger(at, "home_todos", "ops", [...])
        fragment_run.click(at, at.checkbox(key="...").check())

After a fragment-only run, `at` holds just that fragment's elements (as the browser's delta would).
"""

import json
from contextlib import contextmanager
from unittest import mock

from streamlit.components.v2.bidi_component.main import _make_trigger_id
from streamlit.proto.WidgetStates_pb2 import WidgetState
from streamlit.testing.v1 import element_tree, local_script_runner

FRAGMENT_OF = {}        # element id -> id of the fragment it was last drawn in ("" = not in one)
_parse = element_tree.parse_tree_from_messages


def _recording_parse(msgs):
    for m in msgs:
        if not m.HasField("delta") or not m.delta.HasField("new_element"):
            continue
        el = m.delta.new_element
        kind = el.WhichOneof("type")
        eid = getattr(getattr(el, kind), "id", "") if kind else ""
        if eid:
            FRAGMENT_OF[eid] = m.delta.fragment_id
    return _parse(msgs)


@contextmanager
def recording():
    FRAGMENT_OF.clear()
    with mock.patch.object(local_script_runner, "parse_tree_from_messages", _recording_parse):
        yield


def run(at, element_id, widget_states):
    """Rerun with these widget states as the browser would after a change to `element_id`."""
    fid = FRAGMENT_OF.get(element_id, "")
    if not fid:
        return at._run(widget_states)
    real = local_script_runner.RerunData
    with mock.patch.object(local_script_runner, "RerunData", lambda **kw: real(fragment_id=fid, **kw)):
        return at._run(widget_states)


def click(at, widget):
    """After .check() / .set_value() / .click() on a widget: run it (instead of the widget's own .run())."""
    return run(at, widget.id, at._tree.get_widget_states())


def component_id(at, key):
    for el in at.get("bidi_component"):
        if el.proto.id.endswith(f"-{key}"):
            return el.proto.id
    raise LookupError(f"no component with key {key!r} on the page")


def trigger(at, key, event, value):
    """What the component's JS `setTriggerValue(event, value)` does."""
    cid = component_id(at, key)
    states = at._tree.get_widget_states()
    ws = WidgetState(id=_make_trigger_id(cid, "events"))
    ws.json_trigger_value = json.dumps([{"event": event, "value": value}])
    states.widgets.append(ws)
    return run(at, cid, states)


def component_data(at, key):
    """The `data` a component was last drawn with."""
    for el in at.get("bidi_component"):
        if el.proto.id.endswith(f"-{key}"):
            return json.loads(el.proto.json)
    raise LookupError(f"no component with key {key!r} on the page")
