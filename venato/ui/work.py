"""
Start Working: first the session list (say what needs doing, then tick it off; each item can
tick a to-do and fill a bar too), then a game for getting work done, then a plan that forces
delegation. The bars and plan show once the list is done (or if the user skips it).

Everything in the game is the user's own (store.work_bars / work_areas / work_pots, set up in
"Set up" on the page): the areas the page is split into, the bars in each, their targets, the
words that link a list item to a bar, and what the pot is spent on. Nothing is preset. Fill
every level bar and the reward goes into the pot; weekly bars start again every Monday.
Opened by the green button at the bottom of the sidebar. Nothing on it moves.

The page is one custom component (work_component.js/.css); it sends ops, saved here and
acknowledged in `acked` like the to-dos. SQL lives in store.py.
"""

from datetime import datetime
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st

from venato import store

HERE = Path(__file__).parent
PAGE = "Start Working"

_work_component = st.components.v2.component(
    "venato_work",
    html='<div class="sw-root"></div>',
    css=(HERE / "components" / "work_component.css").read_text(encoding="utf-8"),
    js=(HERE / "components" / "work_component.js").read_text(encoding="utf-8"),
)


def apply_op(op):
    """
    {kind: "tap", track, delta}  one more (1) or one fewer (-1) on a bar
    {kind: "spend", amount, pot, note}  pot: one of the user's pots (its key)
    """
    kind = op["kind"]
    if kind == "tap":
        done = store.work_tap(op["track"], 1 if op["delta"] > 0 else -1, op_id=op["opId"])
        if done:
            st.session_state["work_levelled"] = done
    elif kind == "spend":
        try:
            store.work_spend(op["amount"], op["pot"], op.get("note"))
        except ValueError:
            pass                                        # the page checks first; a stale op is dropped


def _on_ops():
    ops = st.session_state["work_game"]["ops"] or []
    acked = st.session_state.setdefault("work_acked", [])
    new = [op for op in ops if op["opId"] not in acked]
    for op in new:
        apply_op(op)
    st.session_state["work_acked"] = (acked + [op["opId"] for op in new])[-500:]


def render_page():
    items = store.session_items()
    finished = bool(items) and all(i["done"] for i in items)
    if not items and not st.session_state.get("ws_skip"):
        _session_start()
        return
    if items and not finished:
        _session_list(items)
        if not st.session_state.get("ws_skip"):
            st.button("Show the bars anyway", key="ws_show", type="tertiary", icon=":material/bar_chart:",
                      on_click=lambda: st.session_state.update(ws_skip=True))
            return
    elif items:
        with st.expander(f"Session done: all {len(items)} ticked off", icon=":material/check_circle:"):
            _session_list(items)
    _game()
    _setup()
    _plan()


# ---------------------------------------------------------------------------
# The session list: say what needs doing, then tick it off.
# ---------------------------------------------------------------------------

SESSION_COLOUR = "#22C55E"


def _record():
    """The Speak / Stop button: the transcript is added to the text box."""
    from venato import voice
    sess = st.session_state
    if voice.recorder.recording:
        if st.button("Stop and write it down", key="ws_stop", type="primary", icon=":material/stop_circle:"):
            try:
                with st.spinner("Writing down what you said…"):
                    text = voice.transcribe(voice.recorder.stop())
                sess["ws_text"] = (sess.get("ws_text", "").rstrip() + "\n" + text).strip()
            except voice.VoiceError as e:
                sess["ws_error"] = str(e)
            st.rerun()
        st.caption(":red[● Listening…] say each thing that needs doing, then click Stop.")
    elif st.button("Speak", key="ws_speak", type="primary", icon=":material/mic:"):
        try:
            voice.recorder.start()
            sess.pop("ws_error", None)
        except voice.VoiceError as e:
            sess["ws_error"] = str(e)
        st.rerun()
    if sess.get("ws_error"):
        st.error(sess["ws_error"])


def _session_start():
    st.title("What needs to get done?", anchor=False)
    st.caption("Say it how you'd say it: \"Firstly…, secondly…, then…\". Each thing becomes an item on your list. "
               "Anything that's already a to-do, or counts towards one of your bars (by the words you gave it), "
               "is linked, so ticking it here ticks that too.")
    _record()
    st.text_area("What needs doing", key="ws_text", height=160, label_visibility="collapsed",
                 placeholder="Firstly, send the invoices. Secondly, write the newsletter. Then call Sam…")
    titles = store.split_session_text(st.session_state.get("ws_text", ""))
    make, skip = st.columns([1, 3], vertical_alignment="center")
    if make.button(f"Make my list ({len(titles)})" if titles else "Make my list", key="ws_make",
                   icon=":material/checklist:", disabled=not titles, width="stretch"):
        store.add_session_items(titles)
        st.session_state.pop("ws_text", None)
        st.rerun()
    skip.button("Skip, straight to the bars", key="ws_skip_btn", type="tertiary",
                on_click=lambda: st.session_state.update(ws_skip=True))


def _link_text(item, todos):
    bits = []
    if item["todo_id"] and item["todo_id"] in todos:
        bits.append(f"ticks to-do “{todos[item['todo_id']]}”")
    if item["track"]:
        bar = store.work_bar(item["track"])
        bits.append(f"+{item['amount']} {bar['name'] if bar else item['track']}")
    return " · ".join(bits)


def _tick_item(item_id, key):
    done = store.tick_session_item(item_id, st.session_state[key])
    if done:
        st.session_state["work_levelled"] = done


def _add_item():
    title = st.session_state.get("ws_new", "").strip()
    if title:
        store.add_session_items(store.split_session_text(title) or [title])
    st.session_state["ws_new"] = ""


def _edit_item(item, open_todos):
    """Fix what an item is linked to (only before it's ticked), or delete it."""
    k = f"wsi_{item['id']}"
    todo_ids = [None, *open_todos]
    todo = st.selectbox("Ticks this to-do", todo_ids, key=f"{k}_todo",
                        index=todo_ids.index(item["todo_id"]) if item["todo_id"] in todo_ids else 0,
                        format_func=lambda i: open_todos[i] if i else "None")
    names = {b["key"]: b["name"] for b in store.work_bars()}
    tracks = [None, *names]
    a, b = st.columns([3, 1])
    track = a.selectbox("Adds to this bar", tracks, key=f"{k}_track",
                        index=tracks.index(item["track"]) if item["track"] in tracks else 0,
                        format_func=lambda t: names[t] if t else "None")
    amount = b.number_input("How many", 1, 100, item["amount"], key=f"{k}_amt")
    save, delete = st.columns(2)
    if save.button("Save", key=f"{k}_save", type="primary", width="stretch"):
        store.update_session_item(item["id"], todo_id=todo, track=track, amount=amount)
        st.rerun()
    if delete.button("Delete", key=f"{k}_del", icon=":material/delete:", width="stretch"):
        store.delete_session_item(item["id"])
        st.rerun()


def _session_list(items):
    done = sum(i["done"] for i in items)
    pct = 100 * done / len(items)
    st.html(f"""<div style="margin:4px 0 10px">
      <div style="display:flex;align-items:baseline;gap:10px;margin-bottom:6px">
        <b style="font-size:1.35rem">This session</b>
        <span style="margin-left:auto;font-weight:700;font-variant-numeric:tabular-nums">{done} of {len(items)} done</span></div>
      <div style="height:22px;border-radius:11px;background:rgba(128,128,128,.18);overflow:hidden">
        <div style="height:100%;width:{pct:.1f}%;background:linear-gradient(90deg,{SESSION_COLOUR},#4ade80);
                    border-radius:11px"></div></div></div>""")
    today = store.local_today()
    open_todos = {t["id"]: t["title"] for t in store.all_open_todos(today)}
    all_titles = {**open_todos, **{i["todo_id"]: (store.get_todo(i["todo_id"]) or {}).get("title", "a deleted to-do")
                                   for i in items if i["todo_id"] and i["todo_id"] not in open_todos}}
    for item in items:
        key = f"ws_{item['id']}"
        st.session_state[key] = item["done"]
        tick, more = st.columns([14, 1], vertical_alignment="center")
        link = _link_text(item, all_titles)
        tick.checkbox(escape(item["title"]) + (f"  \n:gray[{escape(link)}]" if link else ""), key=key,
                      on_change=_tick_item, args=(item["id"], key))
        if not item["done"]:
            with more.popover("", icon=":material/more_horiz:", help="Change what it's linked to, or delete it"):
                _edit_item(item, open_todos)
    st.text_input("Add to the list", key="ws_new", on_change=_add_item, label_visibility="collapsed",
                  placeholder="+ Something else (Enter)")
    if st.button("Start a new list", key="ws_clear", type="tertiary", icon=":material/restart_alt:",
                 help="Clears today's list. Anything you ticked stays ticked."):
        store.clear_session()
        st.session_state.pop("ws_skip", None)
        st.rerun()
    if done == len(items):
        st.success("All done. On to the bars.", icon=":material/celebration:")


def _game():
    bars_list = store.work_bars()
    if not bars_list:
        st.info("No bars yet. Open **Set up** below: make an area or two (e.g. your projects), then the "
                "bars in each, with their targets and the words that link a list item to them.",
                icon=":material/tune:")
        return
    state = store.work_state()
    bars = {}
    for b in bars_list:
        k = b["key"]
        bars[k] = {"name": b["name"], "verb": b["verb"], "weekly": b["weekly"], "total": state["totals"].get(k, 0),
                   "count": (state["weekly"] if b["weekly"] else state["counts"]).get(k, 0),
                   "target": (state["weekly_targets"] if b["weekly"] else state["targets"]).get(k, 1)}
    areas = store.work_areas()
    known = {a["id"] for a in areas}
    panels = [{"id": a["id"], "name": a["name"], "colour": a["colour"],
               "tracks": [b["key"] for b in bars_list if b["area"] == a["id"]]} for a in areas]
    loose = [b["key"] for b in bars_list if b["area"] not in known]
    if loose:
        panels.append({"id": "other", "name": "Other", "colour": "#8B8D98", "tracks": loose})
    panels = [p for p in panels if p["tracks"]]
    data = {k: state[k] for k in ("level", "balance", "wallet", "spent", "reward", "pots")}
    data.update(bars=bars, panels=panels, levelled=st.session_state.pop("work_levelled", None),
                acked=st.session_state.get("work_acked", []))
    _work_component(data=data, key="work_game", on_ops_change=_on_ops)


def _setup():
    """Everything about the game is the user's: areas, bars, pots, the reward and the delegation questions."""
    areas, bars = store.work_areas(), store.work_bars()
    with st.popover("Set up", icon=":material/tune:"):
        st.markdown("**Areas**: the sections the page is split into, each in its own colour (e.g. `#F97316`).")
        area_df = st.data_editor(
            pd.DataFrame([{"id": a["id"], "Area": a["name"], "Colour": a["colour"]} for a in areas],
                         columns=["id", "Area", "Colour"]),
            num_rows="dynamic", hide_index=True, key="ws_setup_areas", width="stretch",
            column_config={"id": None, "Colour": st.column_config.TextColumn(help="A colour like #22C55E; blank picks one")})
        names = {a["id"]: a["name"] for a in areas}
        st.markdown("**Bars**: what you count. *Words* link a session-list item to the bar "
                    "(e.g. `email, newsletter`); a number before one counts that many.")
        bar_df = st.data_editor(
            pd.DataFrame([{"key": b["key"], "Area": names.get(b["area"], ""), "Bar": b["name"],
                           "Button": b["verb"], "Weekly": b["weekly"], "Target": b["base"],
                           "Added per level": b["step"], "Words": ", ".join(b["words"])} for b in bars],
                         columns=["key", "Area", "Bar", "Button", "Weekly", "Target", "Added per level", "Words"]),
            num_rows="dynamic", hide_index=True, key="ws_setup_bars", width="stretch",
            column_config={"key": None,
                           "Area": st.column_config.SelectboxColumn(options=[a["name"] for a in areas] or [""]),
                           "Button": st.column_config.TextColumn(help="The +1 button's text, e.g. 'Sent one'"),
                           "Weekly": st.column_config.CheckboxColumn(help="Starts again every Monday; not part of levels"),
                           "Target": st.column_config.NumberColumn(min_value=1, step=1, help="Level 1's target (weekly: each week's)"),
                           "Added per level": st.column_config.NumberColumn(min_value=0, step=1)})
        pots = st.text_area("What the pot can be spent on (one per line)", "\n".join(p["name"] for p in store.work_pots()),
                            key="ws_setup_pots", height=80)
        reward = st.number_input("Into the pot for each level", 0.0, 1000.0, store.work_reward(), 1.0, key="ws_setup_reward")
        questions = st.text_area("Delegation questions (one per line; one shows at a time, changing every hour)",
                                 "\n".join(store.work_questions()), key="ws_setup_questions", height=120)
        if st.button("Save", type="primary", key="ws_setup_save"):
            area_rows = [r for r in area_df.to_dict("records") if str(r.get("Area") or "").strip()]
            store.save_work_setup(areas=[{"id": r.get("id") if isinstance(r.get("id"), str) else None,
                                          "name": r["Area"], "colour": r.get("Colour")} for r in area_rows])
            by_name = {a["name"].lower(): a["id"] for a in store.work_areas()}
            store.save_work_setup(
                bars=[{"key": r.get("key") if isinstance(r.get("key"), str) else None,
                       "area": by_name.get(str(r.get("Area") or "").lower()), "name": r.get("Bar"),
                       "verb": r.get("Button"), "weekly": bool(r.get("Weekly")),
                       "base": r.get("Target") if pd.notna(r.get("Target")) else 1,
                       "step": r.get("Added per level") if pd.notna(r.get("Added per level")) else 0,
                       "words": str(r.get("Words") or "")} for r in bar_df.to_dict("records")],
                pots=[{"key": next((p["key"] for p in store.work_pots() if p["name"] == line.strip()), None),
                       "name": line} for line in pots.splitlines()],
                reward=reward, questions=questions.splitlines())
            st.rerun()


# ---------------------------------------------------------------------------
# The plan: every task decided as me / delegate / drop.
# ---------------------------------------------------------------------------

def delegate_question(offset=0):
    """One of the user's delegation questions, changing every hour; None if they have none."""
    questions = store.work_questions()
    if not questions:
        return None
    now = datetime.now()
    return questions[(now.toordinal() * 24 + now.hour + offset) % len(questions)]


def nudge_html(text):
    return (f'<div style="padding:10px 14px;border-radius:12px;border-left:4px solid #22c55e;'
            f'background:rgba(34,197,94,.10);font-size:.92rem"><b>Delegate.</b> {escape(text)}</div>')


def _add_task():
    title = st.session_state.get("plan_new", "").strip()
    if title:
        store.add_plan_task(title)
    st.session_state["plan_new"] = ""


def _plan_row(t):
    if t["decision"] is None:
        st.markdown(f"**{escape(t['title'])}**")
        me, dele, drop = st.columns(3)
        with me.popover("Me", icon=":material/person:", width="stretch"):
            st.markdown("**Is this something only you can do?**")
            st.caption("Not something you're best at, not something you enjoy: something that needs you.")
            if st.button("Yes, only I can do this", key=f"pl_me_{t['id']}", type="primary"):
                store.decide_plan_task(t["id"], "me")
                st.rerun()
        with dele.popover("Delegate", icon=":material/group:", width="stretch"):
            who = st.text_input("To whom?", key=f"pl_who_{t['id']}", placeholder="e.g. Sam, a VA, the committee")
            if st.button("Delegate it", key=f"pl_del_{t['id']}", type="primary"):
                store.decide_plan_task(t["id"], "delegate", who)
                st.rerun()
        if drop.button("Drop", key=f"pl_drop_{t['id']}", icon=":material/delete_sweep:", width="stretch"):
            store.decide_plan_task(t["id"], "drop")
            st.rerun()
        return
    label = escape(t["title"]) + (f" :gray[→ {escape(t['who'])}]" if t["decision"] == "delegate" and t["who"] else "")
    tick, x = st.columns([12, 1])
    key = f"pl_done_{t['id']}"
    if tick.checkbox(label, key=key, value=t["done"],
                     help="Tick when it's done" + (" (chase them if it isn't)" if t["decision"] == "delegate" else "")):
        store.finish_plan_task(t["id"])
        st.rerun()
    if x.button("", key=f"pl_x_{t['id']}", icon=":material/close:", type="tertiary", help="Remove"):
        store.delete_plan_task(t["id"])
        st.rerun()


def _triage():
    st.subheader("Plan", anchor=False)
    question = delegate_question()
    if question:
        st.html(nudge_html(question))
    st.text_input("Add a task", key="plan_new", on_change=_add_task, label_visibility="collapsed",
                  placeholder="+ Everything on your plate, one at a time (Enter)")
    tasks = store.plan_tasks()
    undecided = [t for t in tasks if t["decision"] is None]
    delegated = [t for t in tasks if t["decision"] == "delegate"]
    mine = [t for t in tasks if t["decision"] == "me"]
    if undecided:
        st.markdown(f"**Decide** :gray[· {len(undecided)}]")
        for t in undecided:
            with st.container(border=True):
                _plan_row(t)
    if delegated:
        st.markdown(f"**Delegated** :gray[· {len(delegated)} to chase]")
        for t in delegated:
            _plan_row(t)
    if mine:
        st.markdown(f"**Only you** :gray[· {len(mine)}]")
        for t in mine:
            _plan_row(t)
    stats = store.delegation_stats()
    if sum(stats.values()):
        line = (f"Last 7 days: delegated **{stats['delegate']}**, kept **{stats['me']}**, dropped **{stats['drop']}**.")
        if stats["me"] > stats["delegate"] + stats["drop"]:
            line += " You're keeping most of it. What could go?"
        st.caption(line)


def _plan():
    st.write("")
    _triage()


SIDEBAR_CSS = """<style>
  /* Start Working: a small green button under the page list. */
  .st-key-start_working { margin-top: 10px; }
  .st-key-start_working button {
    padding: 4px 14px; min-height: 0; border: none; border-radius: 999px; font-weight: 800;
    color: #04140a; background: linear-gradient(135deg, #3ef07c, #16a34a 55%, #0f7a37);
    box-shadow: 0 0 0 1px rgba(255,255,255,.12) inset, 0 8px 28px rgba(34,197,94,.45);
  }
  .st-key-start_working button:hover { filter: brightness(1.12); color: #021008; }
  .st-key-start_working button p { font-size: 0.85rem; font-weight: 800; }
</style>"""


def _open():
    # Start Working isn't in the sidebar list: the list shows nothing selected while it's open,
    # so clicking any page (even the one you came from) gets you back. Callbacks run before it's drawn.
    st.session_state["page"] = None
    st.session_state["work_open"] = True


def sidebar_button():
    """The green Start Working button, under the page list."""
    st.sidebar.html(SIDEBAR_CSS)
    st.sidebar.button("Start Working", key="start_working", icon=":material/rocket_launch:", on_click=_open)
