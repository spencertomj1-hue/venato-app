"""
The Claude chat bar, pinned to the bottom of every page.

Flow for one message:
  1. The bar sends a "send" trigger (or "mic" start/stop). The callback records
     the message and sets chat_busy = "thinking" (or "transcribing").
  2. The bar is a fragment, so it can redraw on its own. It transcribes, then tries a
     quick command (quick.py: "drank 500ml", "tick gym"... done straight away). Anything
     else starts a Claude job in the background, and the bar redraws every tenth of a
     second with the reply so far. When it's done the whole page reruns, so every page,
     including the timetable grid, shows any changes.
  3. Deletes/overwrites come back as previews; Confirm / Cancel in the panel
     sends a "confirm" trigger that runs or drops them.
"""

import uuid
from pathlib import Path

import streamlit as st

from venato import assistant
from venato import quick
from venato import tools
from venato import undo
from venato import voice

HERE = Path(__file__).parent

_chat_component = st.components.v2.component(
    "venato_chat",
    html='<div class="cb-root"></div>',
    css=(HERE / "components" / "chat_component.css").read_text(encoding="utf-8"),
    js=(HERE / "components" / "chat_component.js").read_text(encoding="utf-8"),
)

MAX_SHOWN = 60   # messages sent to the panel


def _init():
    sess = st.session_state
    sess.setdefault("chat_messages", [])     # [{role: user|assistant|notice|error, text}]
    sess.setdefault("chat_pending", {})      # id -> tools.Pending
    sess.setdefault("chat_busy", None)       # None | "thinking" | "transcribing"
    sess.setdefault("chat_queue", None)      # message waiting for Claude
    sess.setdefault("chat_audio", None)      # recording waiting to be transcribed
    sess.setdefault("chat_notes", [])        # confirm/cancel results to tell Claude next time
    sess.setdefault("chat_error", None)      # shown above the bar
    sess.setdefault("chat_recording", False)
    sess.setdefault("chat_job", None)        # assistant.Job while Claude is answering


def _say(role, text):
    st.session_state["chat_messages"].append({"role": role, "text": text})


# ---------------------------------------------------------------------------
# Component callbacks (run before the page, at the start of the rerun)
# ---------------------------------------------------------------------------

def _on_send():
    value = st.session_state["chat"]["send"]
    text = (value or {}).get("text", "").strip()
    if not text or st.session_state["chat_busy"]:
        return
    _say("user", text)
    st.session_state["chat_queue"] = text
    st.session_state["chat_busy"] = "thinking"
    st.session_state["chat_error"] = None


def _on_mic():
    action = (st.session_state["chat"]["mic"] or {}).get("action")
    sess = st.session_state
    sess["chat_error"] = None
    try:
        if action == "start":
            voice.recorder.start()
            sess["chat_recording"] = True
        elif action == "stop":
            sess["chat_recording"] = False
            sess["chat_audio"] = voice.recorder.stop()
            sess["chat_busy"] = "transcribing"
    except voice.VoiceError as e:
        sess["chat_recording"] = voice.recorder.recording
        sess["chat_error"] = str(e)


def _on_confirm():
    value = st.session_state["chat"]["confirm"] or {}
    pending = st.session_state["chat_pending"].pop(value.get("id"), None)
    if not pending:
        return
    if not value.get("ok"):
        _say("notice", "Cancelled.")
        st.session_state["chat_notes"].append(f"The user cancelled: {pending.summary}.")
        return
    try:
        undo.checkpoint(pending.summary)          # Claude's change can be undone too
        result = pending.run()
        _say("notice", f"✓ {result.text}")
        st.session_state["chat_refresh"] = True     # redraw the whole page, not just the bar
        st.session_state["chat_notes"].append(f"The user confirmed, and it was done: {pending.summary}.")
    except tools.ToolError as e:
        _say("error", f"Couldn't do that: {e}")


# ---------------------------------------------------------------------------
# The slow work, done after the bar is drawn
# ---------------------------------------------------------------------------

def _transcribe():
    sess = st.session_state
    try:
        text = voice.transcribe(sess["chat_audio"])
        _say("user", text)                  # show the transcript as the user's message
        sess["chat_queue"] = text
        sess["chat_busy"] = "thinking"
    except voice.VoiceError as e:
        sess["chat_error"] = str(e)
        sess["chat_busy"] = None
    finally:
        sess["chat_audio"] = None


POLL = 0.1   # seconds between redraws while Claude writes


def _tab_key():
    """One Claude session per browser tab."""
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        return get_script_run_ctx().session_id
    except Exception:
        return "default"


def _record(turn):
    """Put a finished turn's reply and previews in the chat."""
    sess = st.session_state
    if turn.error:
        _say("error", turn.error)
    else:
        sess["chat_notes"] = []
        if turn.reply:
            _say("assistant", turn.reply)
        for p in turn.pending:
            sess["chat_pending"][uuid.uuid4().hex] = p
    sess["chat_queue"] = None
    sess["chat_busy"] = None
    sess["chat_job"] = None


def _ask_claude():
    """Answer the waiting message: a quick command straight away, or start a Claude job.
    True when the message is finished with (the page should redraw)."""
    sess = st.session_state
    text = sess["chat_queue"]
    reply = quick.handle(text)
    if reply:
        _record(reply)
        return True
    prompt = text
    if sess["chat_notes"]:
        # Let Claude know what happened to its previews since the last reply.
        prompt = "(Since your last reply: " + " ".join(sess["chat_notes"]) + ")\n\n" + prompt
    # Earlier messages go along as context when a session starts (the chat is only kept in memory).
    history = [(m["role"], m["text"]) for m in sess["chat_messages"]]
    if history and history[-1] == ("user", text):
        history = history[:-1]                 # that's the message being sent now
    sess["chat_job"] = assistant.start_turn(prompt, history, key=_tab_key())
    return False


def render(inline=False):
    """
    inline=False: the bar pinned to the bottom of the page (every page but Home).
    inline=True:  a full-height chat panel in place, e.g. the Home page's right column.
    """
    _init()
    if not inline:
        # Leave room under the page so the bar never covers content.
        st.html("<style>.stMainBlockContainer { padding-bottom: 8rem; }</style>")
    # While Claude is answering, the bar redraws itself every POLL seconds (only the bar).
    polling = st.session_state["chat_job"] is not None
    st.fragment(_bar, run_every=POLL if polling else None)(inline, polling)


def _bar(inline, polling):
    sess = st.session_state
    job = sess["chat_job"]
    data = {
        "inline": inline,
        "messages": sess["chat_messages"][-MAX_SHOWN:],
        "pending": [{"id": pid, "summary": p.summary} for pid, p in sess["chat_pending"].items()],
        "busy": sess["chat_busy"],
        "partial": job.partial if job else "",
        "status": job.status if job else "",
        "recording": sess["chat_recording"],
        "error": sess["chat_error"],
    }
    _chat_component(          # drawn first, so "Transcribing" / "Thinking" shows during the work below
        data=data, key="chat",
        on_send_change=_on_send, on_mic_change=_on_mic, on_confirm_change=_on_confirm,
    )

    if sess.pop("chat_refresh", False):
        st.rerun()                      # a confirmed change: show it on the page
    if sess["chat_busy"] == "transcribing":
        _transcribe()
        st.rerun()                      # show the transcript, then answer it
    if sess["chat_busy"] == "thinking":
        if sess["chat_job"] is None and _ask_claude():
            st.rerun()                  # a quick command: show the change on the page
        job = sess["chat_job"]
        if job and job.done:
            _record(job.turn)
            st.rerun()                  # show the reply and any changes on the page
        if not polling:
            st.rerun()                  # start redrawing the bar as the reply comes in
