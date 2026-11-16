"""Strava on screen: Settings → Strava (connect steps) and the sync on app load. strava.py talks to Strava."""

import streamlit as st

from venato import outlook
from venato import strava
from venato import system


def autosync():
    """On app load: sync if it's been 30 minutes. Returns True if anything new came in."""
    try:
        status = strava.sync()
    except Exception:
        return False
    if status:
        st.session_state["strava_status"] = status
    return bool(status and status.get("ok") and status.get("activities"))


def settings_section():
    st.subheader("Strava")
    if strava.connected():
        st.success("Strava is connected. New activities come in every 30 minutes; runs tick off that day's "
                   "training run and show on the Stats page.", icon=":material/check_circle:")
        status = st.session_state.get("strava_status") or {}
        if status.get("error"):
            st.warning(status["error"], icon=":material/cloud_off:")
        st.caption(f"Last synced {outlook.ago(strava.last_synced())}.")
        a, b = st.columns(2)
        if a.button("Sync now", icon=":material/sync:", key="strava_sync"):
            st.session_state["strava_status"] = strava.sync(force=True)
            st.rerun()
        if b.button("Disconnect", icon=":material/link_off:", key="strava_disconnect"):
            strava.disconnect()
            st.rerun()
        return

    st.markdown(
        "Bring in your **runs** (and other activities) from Strava. Runs show on the Stats page and tick off "
        "that day's training run with the real distance.\n\n"
        "**One-time setup (about 2 minutes):**\n"
        "1. Go to [strava.com/settings/api](https://www.strava.com/settings/api) and sign in.\n"
        "2. Fill in the form: **Application Name** e.g. *Venato*, **Category** *Training*, **Website** "
        "`http://localhost`, and **Authorization Callback Domain** `localhost`. Upload any icon if it asks.\n"
        "3. Save, then copy the **Client ID** and **Client Secret** below."
    )
    app = strava.app_credentials()
    with st.form("strava_app", border=False):
        client_id = st.text_input("Client ID", value=app["client_id"] if app else "")
        client_secret = st.text_input("Client Secret", type="password", placeholder="(saved)" if app else "",
                                      help=f"Kept in your {system.SECRET_STORE}.")
        if st.form_submit_button("Save" if not app else "Save changes"):
            try:
                strava.save_app(client_id, client_secret or (app or {}).get("client_secret"))
                st.rerun()
            except strava.StravaError as e:
                st.error(str(e))
    if not app:
        return

    result = strava.connect_result()
    if result:
        ok, message = result
        strava.stop_connect()
        st.session_state.pop("strava_url", None)
        if ok:
            st.session_state["strava_status"] = strava.sync(force=True)
            st.rerun()
        st.error(message)
    if st.session_state.get("strava_url") and not result:
        st.info("Strava's Authorize page opened in your browser. Click **Authorize** there (leave \"View data about "
                "your activities\" ticked), then come back and press **I've authorized**.", icon=":material/open_in_new:")
        st.link_button("Open Strava's Authorize page again", st.session_state["strava_url"])
        if st.button("I've authorized", type="primary"):
            st.rerun()
    elif st.button("Connect Strava", type="primary", icon=":material/link:"):
        try:
            st.session_state["strava_url"] = strava.start_connect()
        except strava.StravaError as e:
            st.error(str(e))
        st.rerun()
