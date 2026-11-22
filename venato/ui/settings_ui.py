"""
First-run setup wizard and the Settings page.

The setup wizard (steps in ui/onboarding.py) shows once (settings.json "wizard_done") and can be
reopened from Settings → About; running it again only adds things. The Claude assistant, calendar and
microphone are set up here in Settings, not in the wizard.

The Claude assistant is optional (settings.json "ai_enabled"): everything in
Venato works by hand, and switching it on adds the chat box and voice input.
"""

import logging
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from venato import assistant
from venato import feedback
from venato import outlook
from venato import setup_checks
from venato import regional
from venato import store
from venato import undo
from venato import system
from venato.ui import onboarding
from venato.ui import kit

# ---------------------------------------------------------------------------
# Shared sections
# ---------------------------------------------------------------------------

KEY_WAY, CODE_WAY = "Paste an API key (easiest)", "Use my Claude subscription (Claude Code)"


def claude_section(prefix):
    """Is Claude ready? If not, two ways to set it up: an Anthropic API key, or Claude Code."""
    status = st.session_state.get(f"{prefix}_claude") or setup_checks.claude_status()
    st.session_state[f"{prefix}_claude"] = status

    def recheck():
        st.session_state.pop(f"{prefix}_claude", None)

    if status["logged_in"]:
        how = "an Anthropic API key" if status["account"] == "API key" else f"Claude Code ({status['account']})"
        st.success(f"Claude is ready, using {how}.", icon=":material/check_circle:")
        if assistant.saved_api_key():
            if st.button("Remove the API key", key=f"{prefix}_key_forget", icon=":material/key_off:"):
                assistant.forget_api_key()
                recheck()
                st.rerun()
        return

    st.warning(status["note"], icon=":material/warning:")
    way = st.radio("How should Venato talk to Claude?", [KEY_WAY, CODE_WAY], key=f"{prefix}_claude_way")
    if way == KEY_WAY:
        st.markdown(
            "1. Go to [console.anthropic.com](https://console.anthropic.com), sign up or sign in, and add some credit "
            "(Anthropic charges per message; you can set a monthly limit there).\n"
            "2. Open **API keys** → **Create key**, and copy it.\n"
            "3. Paste it here. It's checked with Anthropic, then kept in your "
            f"{system.SECRET_STORE}, never in a file."
        )
        with st.form(f"{prefix}_key_form", clear_on_submit=True, border=False):
            key = st.text_input("Anthropic API key", type="password", placeholder="sk-ant-…")
            if st.form_submit_button("Save key", icon=":material/key:") and key.strip():
                ok, message = assistant.check_api_key(key)
                if ok:
                    assistant.save_api_key(key)
                    recheck()
                    st.rerun()
                st.error(message, icon=":material/error:")
    else:
        st.markdown("If you pay for Claude (Pro or Max), Venato can use that through **Claude Code**, Anthropic's "
                    f"command-line app. Open **{setup_checks.SHELL}** and run these one at a time (use the copy "
                    "button on each):")
        if not status["found"]:
            kit.subhead("1. Install Claude Code")
            st.code(setup_checks.INSTALL_CMD, language="powershell" if system.IS_WINDOWS else "bash")
        st.markdown(f"**{'2' if not status['found'] else '1'}. Sign in** (opens your browser)")
        st.code(setup_checks.LOGIN_CMD, language="bash")
        if st.button("Check again", key=f"{prefix}_claude_check", icon=":material/refresh:"):
            recheck()
            st.rerun()
    st.caption("Everything else in Venato works without Claude.")


def outlook_guide(prefix):
    """Step-by-step guide to publishing an Outlook calendar, plus the paste box."""
    st.markdown(
        "1. Open [outlook.office.com](https://outlook.office.com) and sign in.\n"
        "2. Click the **Settings** cog → **Calendar** → **Shared calendars**.\n"
        "3. Under **Publish a calendar**, pick your calendar and **Can view all details**, then click **Publish**.\n"
        "4. Copy the **ICS** link (the one ending in **.ics**, not .html).\n"
        "5. Paste it below and press **Connect**."
    )
    st.info("Anyone who has this link can see your calendar, so keep it private. To revoke it, go back to "
            "Shared calendars and click **Unpublish** (or **Reset links** to get a new one).",
            icon=":material/visibility:")

    with st.form(f"{prefix}_outlook_form", clear_on_submit=True, border=False):
        pasted = st.text_input("ICS link", placeholder="https://outlook.office365.com/…/calendar.ics",
                               type="password", help="Hidden so the link isn't shown on screen.")
        go = st.form_submit_button("Connect", type="primary", icon=":material/link:")
    if go:
        try:
            url, note = outlook.check_link(pasted)
            if note:
                st.info(note, icon=":material/swap_horiz:")
            with st.spinner("Checking the link with Outlook…"):
                found = outlook.try_link(url)
                outlook.connect(url, found["data"])
            st.session_state[f"{prefix}_found"] = found
        except outlook.LinkError as e:
            st.error(str(e), icon=":material/error:")
        except outlook.SyncError as e:
            st.error(outlook.friendly(e), icon=":material/error:")
        except Exception as e:
            st.error(f"That didn't work: the link didn't give a calendar Venato can read ({type(e).__name__}).",
                     icon=":material/error:")

    found = st.session_state.get(f"{prefix}_found")
    if found and outlook.ics_url():
        st.success(f"Connected. {outlook.found_text(found)}", icon=":material/check_circle:")
        for ev in found["preview"]:
            st.markdown(f"- **{ev['title']}** · {ev['when']}")


def other_calendars(prefix):
    """Google, iCloud and other published calendars, shown alongside Outlook in the timetable."""
    items = outlook.extra_calendars()
    for c in items:
        x, y = st.columns([4, 1], vertical_alignment="center")
        x.markdown(f":material/event: **{c['name']}**")
        if y.button("Remove", key=f"{prefix}_cal_rm_{c['id']}", icon=":material/link_off:"):
            outlook.remove_calendar(c["id"])
            st.session_state.pop("outlook_status", None)
            st.rerun()
    with st.expander("Add a Google, Apple (iCloud) or other calendar", icon=":material/add:", expanded=False):
        st.markdown(
            "**Google:** calendar.google.com → ⚙ Settings → your calendar → **Integrate calendar** → copy the "
            "**Secret address in iCal format**.  \n"
            "**Apple:** Calendar app (Mac) or iCloud.com → right-click the calendar → **Share Calendar** → tick "
            "**Public Calendar** → copy the link (webcal://…).  \n"
            "**Anything else:** any calendar link ending in .ics.")
        st.info("Anyone with the link can see that calendar, so it's kept in the "
                f"{system.SECRET_STORE}, never shown again. Venato only reads it.", icon=":material/visibility:")
        with st.form(f"{prefix}_cal_add", clear_on_submit=True, border=False):
            a, b = st.columns([1, 3])
            name = a.text_input("Name", placeholder="e.g. Personal")
            link = b.text_input("Calendar link", type="password", placeholder="https://calendar.google.com/…/basic.ics")
            go = st.form_submit_button("Add calendar", icon=":material/link:")
        if go:
            try:
                url, provider = outlook.check_any_link(link)
                with st.spinner("Checking the link…"):
                    found = outlook.try_link(url)
                    st.session_state["outlook_status"] = outlook.add_calendar(name or provider, url, found["data"])
                st.success(f"Added. {outlook.found_text(found)}", icon=":material/check_circle:")
                st.rerun()
            except outlook.LinkError as e:
                st.error(str(e), icon=":material/error:")
            except outlook.SyncError as e:
                st.error(outlook.friendly(e).replace("Outlook", "the calendar"), icon=":material/error:")
            except Exception as e:
                st.error(f"That link didn't give a calendar Venato can read ({type(e).__name__}).", icon=":material/error:")


def calendar_status(prefix):
    """Connected? Last sync, Sync now, Disconnect."""
    if not outlook.ics_url():
        st.markdown(":material/link_off: **Not connected.** Follow the steps below to show your Outlook "
                    "calendar in the timetable.")
        return False
    status = st.session_state.get("outlook_status") or {}
    st.markdown(f":material/check_circle: **Connected** · last synced {outlook.ago(outlook.last_synced())}")
    if status.get("error"):
        st.caption(f"Last attempt failed: {status['error']}")
    a, b, _ = st.columns([1, 1, 3])
    if a.button("Sync now", key=f"{prefix}_sync", icon=":material/sync:"):
        st.session_state["outlook_status"] = outlook.sync()
        st.rerun()
    if b.button("Disconnect", key=f"{prefix}_disconnect", icon=":material/link_off:"):
        st.session_state[f"{prefix}_confirm_disconnect"] = True
    if st.session_state.get(f"{prefix}_confirm_disconnect"):
        st.warning(f"Disconnect removes the link from the {system.SECRET_STORE} and the imported events from the timetable. "
                   "Your own blocks aren't touched.")
        c, d, _ = st.columns([1, 1, 3])
        if c.button("Yes, disconnect", key=f"{prefix}_disconnect_yes", type="primary"):
            outlook.disconnect()
            st.session_state.pop("outlook_status", None)
            st.session_state.pop(f"{prefix}_found", None)
            st.session_state[f"{prefix}_confirm_disconnect"] = False
            st.rerun()
        if d.button("Cancel", key=f"{prefix}_disconnect_no"):
            st.session_state[f"{prefix}_confirm_disconnect"] = False
            st.rerun()
    return True


def mic_section(prefix):
    st.markdown("Click the mic in the chat bar to speak instead of typing. The first time, your computer may ask whether "
                f"**Venato may use the microphone**: click **Allow**. Your voice is turned into text on this {system.COMPUTER} "
                "and never uploaded.")
    if not setup_checks.speech_model_downloaded():
        st.caption("The first test downloads the speech model (about 470 MB), so it can take a minute.")
    if st.button("Test microphone", key=f"{prefix}_mic", icon=":material/mic:"):
        with st.spinner("Recording for 3 seconds… say something!"):
            result = setup_checks.mic_test()
        st.session_state[f"{prefix}_mic_result"] = result
    result = st.session_state.get(f"{prefix}_mic_result")
    if result:
        if not result["ok"]:
            st.error(result["error"], icon=":material/mic_off:")
        elif result["text"]:
            st.success(f"Heard you: “{result['text']}”", icon=":material/check_circle:")
        else:
            st.warning(result["error"] or "The mic works, but no words were recognised.", icon=":material/warning:")


# ---------------------------------------------------------------------------
# First-run wizard
# ---------------------------------------------------------------------------

def ai_switch(prefix):
    """The on/off switch for the optional Claude assistant; True if it's on."""
    on = store.ai_enabled() if "ai_enabled" in store.load_settings() else True
    new = st.toggle("Use the Claude assistant", value=on, key=f"{prefix}_ai_on",
                    help="Adds a chat box (and voice input) where you can ask Claude to make changes for you. "
                         "Everything also works without it.")
    if new != store.load_settings().get("ai_enabled"):
        store.save_settings(ai_enabled=new)
    return new


AI_PITCH = ("Venato works fully by hand. Optionally, switch on the **Claude assistant** to get a chat box "
            "where you type (or say) things like *\"I went to the gym 6 till 7\"*, *\"fit 6 hours of revision "
            "into next week\"* or *\"move my essay to Friday\"*, and Claude makes the changes for you. "
            "It needs an Anthropic API key or a Claude subscription, and the messages you send go to Anthropic.")


def needs_wizard():
    return st.session_state.get("wizard_open") or not setup_checks.load_settings().get("wizard_done")


def _finish(prefill_home=True):
    """Setup is over (done or skipped): the core blocks (Modules too for a student), the assistant off, no wizard again.
    Setup only adds: a block choice already made is kept, and a student's Modules block is added to it."""
    if "ai_enabled" not in setup_checks.load_settings():
        setup_checks.save_settings(ai_enabled=False)  # skipped the question: the assistant stays off
    from venato import blocks
    done = setup_checks.load_settings()
    student = onboarding.is_student()
    if not done.get("wizard_done") and "blocks" not in done:
        blocks.save(blocks.STARTER + (["grades"] if student else []))   # first setup; change them in Settings
    elif student and not blocks.is_on("grades"):
        blocks.save(blocks.chosen_keys() + ["grades"])
    if prefill_home and "home" not in done:           # only a real finish, and only if Home was never arranged
        try:
            onboarding.prefill_home([k for k, _ in onboarding.home_picks()])
        except Exception:                             # Home keeps its default; setup is done either way
            logging.getLogger(__name__).warning("Setup couldn't prefill Home", exc_info=True)
    setup_checks.save_settings(wizard_done=True)
    st.session_state["wizard_open"] = False
    onboarding.restart()


def _skip():
    _finish(prefill_home=False)


def wizard():
    onboarding.wizard(_finish, _skip)


# ---------------------------------------------------------------------------
# Settings page
# ---------------------------------------------------------------------------

def reminders_section():
    """Desktop notifications before Plan blocks and Outlook events (venato/notify.py)."""
    from venato import notify
    on, minutes = notify.settings()
    st.write(f"A notification on your {system.COMPUTER} shortly before each block in your Plan "
             "(and each Outlook event) starts, while Venato is open.")
    new_on = st.toggle("Remind me before blocks start", value=on, key="remind_on")
    new_minutes = st.number_input("Minutes before", 0, 60, minutes, step=1, key="remind_minutes",
                                  disabled=not new_on, help="0 = when the block starts.")
    if (new_on, new_minutes) != (on, minutes):
        store.save_settings(reminders=new_on, reminder_minutes=int(new_minutes))
        st.toast("Saved", icon=":material/check_circle:")
    if st.button("Send a test notification", icon=":material/notifications_active:"):
        if system.notify("Venato", "Reminders are working."):
            st.success("Sent. If nothing popped up, check your system's notification settings"
                       + (" (System Settings → Notifications → Script Editor)." if system.IS_MAC else "."))
        else:
            st.error(f"Couldn't show a notification on this {system.COMPUTER}.")


def daily_log_section():
    """Sleep and water are optional extras on the Daily Log; the journal and habits are always there."""
    st.subheader("Daily Log", anchor=False)
    st.write("The Daily Log is a journal. You can also record how long you slept and how much water you drank. "
             "Switching one off hides it everywhere (the page, calendar, charts, review and assistant). "
             "What you've already recorded is kept.")
    sleep = st.toggle("Track sleep", value=store.tracks_sleep(), key="log_sleep_on")
    water = st.toggle("Track water", value=store.tracks_water(), key="log_water_on")
    if (sleep, water) != (store.tracks_sleep(), store.tracks_water()):
        store.set_tracking(sleep=sleep, water=water)
        st.toast("Saved", icon=":material/check_circle:")
        st.rerun()


def appearance_section():
    from venato.ui import appearance
    st.subheader("Appearance", anchor=False)
    current = appearance.mode()
    picked = st.segmented_control("Theme", appearance.MODES, default=current, key="set_theme",
                                  help="System follows your computer's light or dark mode.")
    if picked and picked != current:
        appearance.set_mode(picked)
        st.rerun()                               # the sync script then switches the theme
    size = appearance.text_size()
    new_size = st.segmented_control("Text size", list(appearance.SIZES), default=size, key="set_text_size")
    if new_size and new_size != size:
        appearance.set_text_size(new_size)
        st.rerun()
    st.markdown("The quick brown fox jumps over the lazy dog: this is how text looks at this size.")


def region_section():
    """Time zone (and, below, how dates, times and units are shown)."""
    import zoneinfo
    st.subheader("Time zone")
    st.caption("Decides what \"today\" is, and the times of your Outlook events.")
    chosen = store.load_settings().get("timezone")
    computer = store.computer_zone_name()
    own = st.toggle(f"Use my computer's time zone ({computer})", value=not chosen, key="region_tz_auto")
    if own and chosen:
        store.save_settings(timezone=None)
        st.rerun()
    if not own:
        zones = sorted(z for z in zoneinfo.available_timezones() if "/" in z and not z.startswith(("Etc/", "SystemV/")))
        current = chosen or computer
        pick = st.selectbox("Time zone", zones, index=zones.index(current) if current in zones else None,
                            placeholder="Type a city, e.g. New_York", key="region_tz")
        if pick and pick != chosen:
            store.save_settings(timezone=pick)
            st.rerun()
    now = store.local_now()
    st.markdown(f"It's **{regional.long_date(now)}, {regional.time(f'{now:%H:%M}')}** in "
                f"{store.zone_name().replace('_', ' ')}.")

    st.subheader("Dates, times and units")
    a, b = st.columns(2)
    week = a.segmented_control("Weeks start on", list(regional.WEEK_STARTS), default=regional.week_start(),
                               key="region_week", help="For the timetable, the calendar, weekly to-dos and habits.")
    clock = b.segmented_control("Clock", regional.CLOCKS, default=regional.clock(), key="region_clock")
    a, b = st.columns(2)
    fmt = a.selectbox("Dates", list(regional.DATE_FORMATS), index=list(regional.DATE_FORMATS).index(regional.date_format()),
                      format_func=lambda f: f"{f} ({regional.DATE_FORMATS[f]})", key="region_date")
    water = b.segmented_control("Water", regional.WATER_UNITS, default=regional.water_unit(), key="region_water")
    changed = False
    if week and week != regional.week_start():
        store.set_week_start(week)           # also moves weekly to-dos to the new weeks
        changed = True
    for key, value, current in (("clock", clock, regional.clock()), ("date_format", fmt, regional.date_format()),
                                ("water_unit", water, regional.water_unit())):
        if value and value != current:
            store.save_settings(**{key: value})
            changed = True
    if changed:
        st.rerun()
    sample = store.local_today()
    st.caption(f"Example: {regional.long_date(sample)} · {regional.numeric_date(sample)} · "
               f"{regional.time_range('09:00', '17:30')} · {regional.water_text(2.0)}")

    st.subheader("Timetable hours")
    start, end = store.day_hours()
    hours = list(range(24))
    a, b = st.columns(2)
    new_start = a.selectbox("Day starts at", hours, index=start, format_func=lambda h: regional.time(f"{h:02d}:00"),
                            key="region_day_start")
    new_end = b.selectbox("Day ends at", hours, index=end, key="region_day_end",
                          format_func=lambda h: regional.time(f"{h:02d}:00")
                          + (" (next day)" if h <= new_start else ""))
    length = store.day_length(new_start, new_end)
    if (new_start, new_end) != (start, end):
        if length < store.MIN_DAY_HOURS:
            st.error(f"Make the day at least {store.MIN_DAY_HOURS} hours long.")
        else:
            store.save_settings(day_start=new_start, day_end=new_end, sleep_asked=True)
            st.rerun()
    st.caption(f"{length} hours a day. Anything after midnight counts as the day before, like a late night. "
               "Blocks outside these hours stay saved; widen the hours again to see them.")

    st.subheader("Goals and your timetable")
    inflate = store.load_settings().get("goal_inflate", True)
    new = st.toggle("Plan extra for time that usually slips", value=inflate, key="region_goal_inflate",
                    help="Goals that count timetable hours compare what you planned with what you did over the "
                         "last 6 weeks. If you usually do 60% of what you plan, Fit time suggests planning more "
                         "so you still land the hours. Off: plan exactly what the goal needs.")
    if new != inflate:
        store.save_settings(goal_inflate=new)
        st.rerun()


def _updates_section():
    from venato import updates
    current = updates.current_version()
    st.markdown(f"**Version:** {current if current != 'dev' else 'running from the source code (update with git pull)'}")
    on = st.toggle("Check for new versions once a day", value=updates.enabled(), key="about_updates",
                   help="Asks GitHub for the latest release. Nothing about you is sent.")
    if on != updates.enabled():
        store.save_settings(update_check=on)
    if current not in ("dev", "0.0.0") and st.button("Check now", icon=":material/refresh:", key="about_check"):
        latest = updates.check(force=True)
        if not latest:
            st.warning("Couldn't reach GitHub. Are you online?")
        elif updates.is_newer(latest["version"], current):
            st.success(f"Venato {latest['version']} is available: [download it]({latest['url']}).")
        else:
            st.success("You have the latest version.")


def page_settings():
    st.header("Settings", anchor=False)
    ai = store.ai_enabled()
    pages = [("blocks", ":material/widgets: Blocks"), ("look", ":material/palette: Appearance"),
             ("region", ":material/public: Region"), ("log", ":material/edit_calendar: Daily Log"),
             ("cal", ":material/calendar_month: Calendar"), ("claude", ":material/chat: Assistant")]
    if ai:
        pages.append(("mic", ":material/mic: Voice"))       # voice input is for the assistant
    pages += [("remind", ":material/notifications: Reminders"), ("data", ":material/database: Data"),
              ("about", ":material/info: About")]
    opened = dict(pages).get(st.session_state.pop("settings_tab", None))     # e.g. Home's "try the assistant" card
    tabs = dict(zip([k for k, _ in pages], st.tabs([n for _, n in pages], default=opened)))
    look, region, log, cal, claude, mic, remind, data, about = (
        tabs.get(k) for k in ("look", "region", "log", "cal", "claude", "mic", "remind", "data", "about"))
    with tabs["blocks"]:
        from venato.ui import blocks_ui
        blocks_ui.section("set")
    with look:
        appearance_section()
    with region:
        region_section()
    with log:
        daily_log_section()
    with cal:
        st.subheader("Outlook calendar", anchor=False)
        connected = calendar_status("set")
        if connected:
            with st.expander("Connect a different calendar", icon=":material/link:"):
                outlook_guide("set")
        else:
            outlook_guide("set")
        st.subheader("Other calendars", anchor=False)
        other_calendars("set")
    with claude:
        st.subheader("Claude assistant", anchor=False)
        st.markdown(AI_PITCH)
        if ai_switch("set") != ai:
            st.rerun()                                   # show or hide the chat box straight away
        if ai:
            quick_on = st.toggle(
                "Quick commands", value=store.load_settings().get("quick_commands", True), key="set_quick",
                help="Short everyday messages like \"drank 500ml\" or \"tick gym\" are done "
                     "straight away without asking Claude (their reply starts with ⚡). Anything else still goes to Claude.")
            if quick_on != store.load_settings().get("quick_commands", True):
                store.save_settings(quick_commands=quick_on)
            claude_section("set")
    if mic:
        with mic:
            st.subheader("Voice input", anchor=False)
            mic_section("set")
    with remind:
        st.subheader("Reminders", anchor=False)
        reminders_section()
    with data:
        _data_section()
    with about:
        st.subheader("About Venato", anchor=False)
        st.markdown(
            "A tracker for university life: a timetable with Plan and Actual, to-dos and deadlines, goals, "
            "focus sessions, grades, a weekly review, and an optional Claude assistant. "
            f"Built with Streamlit and SQLite; runs entirely on your {system.COMPUTER}.\n\n"
            "Open source under the **MIT licence**."
        )
        _updates_section()
        st.link_button("Send feedback", feedback.feedback_url(), icon=":material/rate_review:",
                       help="Opens a short form in your browser. Nothing is sent from the app.")
        st.caption("Setup only adds things: nothing you have is deleted.")
        if st.button("Run setup again", icon=":material/restart_alt:"):
            onboarding.restart()
            st.session_state["wizard_open"] = True
            st.rerun()


def _data_section():
    st.subheader("Where your data lives", anchor=False)
    st.markdown(f":material/folder: `{store.DATA_DIR}`")
    a, b, c = st.columns(3)
    if a.button("Open data folder", icon=":material/folder_open:"):
        setup_checks.open_folder(store.DATA_DIR)
    if b.button("Back up now", icon=":material/backup:"):
        path = setup_checks.backup_now()
        st.toast(f"Backed up to {path.name}", icon=":material/check_circle:")
    if c.button("Open backups folder", icon=":material/inventory_2:"):
        setup_checks.open_folder(setup_checks.backups_dir())
    backups = setup_checks.list_backups()
    st.caption(f"{len(backups)} backup{'s' if len(backups) != 1 else ''}"
               + (f", latest {backups[0].name}" if backups else "") + ".")
    _backup_settings()

    st.subheader("Export", anchor=False)
    st.write("Your journal and habits as one CSV: one row per date, one column per habit (plus sleep and water, if you track them).")
    csv = store.load_all_data().to_csv(index=False)
    st.download_button("Download CSV", csv, file_name=f"venato_export_{store.local_today()}.csv",
                       mime="text/csv", icon=":material/download:")

    st.subheader("Import", anchor=False)
    st.write(
        f"Use the same format as the export: a `date` column (YYYY-MM-DD), optional "
        f"`notes`, `sleep` (hours) and `water` (litres) columns, and `{store.HABIT_PREFIX}<name>` columns "
        f"containing true/false or 1/0."
    )
    uploaded = st.file_uploader("CSV file", type="csv")
    mode = st.radio("Import mode", ["Merge (update matching dates)", "Replace all existing data"])
    if uploaded and st.button("Import", icon=":material/upload:"):
        new = pd.read_csv(uploaded)
        if "date" not in new.columns:
            st.error("The CSV needs a `date` column.")
        else:
            undo.checkpoint(f"Imported {len(new)} rows" + (" (replacing everything)" if mode.startswith("Replace") else ""))
            store.save_all_data(new, replace=mode.startswith("Replace"))
            st.success(f"Imported {len(new)} rows.")

    st.subheader("Journal", anchor=False)
    entries = store.journal_entries()
    st.write(f"Your journal (the Daily Log's notes) as one text file, oldest first ({len(entries)} entr{'y' if len(entries) == 1 else 'ies'}).")
    text = "\n\n".join(f"# {e['date']}\n\n{e['text']}" for e in reversed(entries))
    st.download_button("Download journal", text, file_name=f"venato_journal_{store.local_today()}.md",
                       mime="text/markdown", icon=":material/download:", disabled=not entries)

    _csv_section(
        "To-dos", "todos", store.load_todos, store.save_todos, ["title", "period"],
        "`title`, `period` (daily, weekly or monthly) and `period_start` (YYYY-MM-DD, any day in the period); "
        "optional `id`, `notes`, `done`, `done_at`, `repeat`, `ord` and `created_at`.",
    )
    _csv_section(
        "Goals", "life_goals", store.load_life_goals, store.save_life_goals, ["title", "start", "end_date"],
        "Long-term goals: `title`, `start` and `end_date` (YYYY-MM-DD); optional `id`, `why`, `ord`, `created_at` "
        "and `archived`. Import these before targets, so targets find their goal.",
    )
    _csv_section(
        "Targets", "goals", store.load_goals, store.save_goals, ["title", "target"],
        "`title`, `target` and `due` (the deadline, YYYY-MM-DD; or, from older exports, `period`: monthly or "
        "yearly); optional `period_start` (the day it was set), `id`, `unit`, `progress`, `habit` (a habit's name, "
        "to count its ticks), `category`, `label`, `life_goal` (the title of the goal it's under), `ord` and "
        "`created_at`.",
    )


def _backup_settings():
    """Automatic daily backups, and where backups go."""
    st.subheader("Automatic backups", anchor=False)
    on, keep = setup_checks.auto_backup_settings()
    new_on = st.toggle("Back up automatically once a day", value=on, key="backup_auto",
                       help=f"While Venato is open. Keeps the newest {keep}; older ones are deleted.")
    new_keep = st.columns([1, 3])[0].number_input("Backups to keep", 3, 365, keep, step=1, key="backup_keep",
                                                  disabled=not new_on)
    if (new_on, new_keep) != (on, keep):
        store.save_settings(auto_backup=new_on, backup_keep=int(new_keep))
        st.toast("Saved", icon=":material/check_circle:")

    folder = setup_checks.backups_dir()
    st.markdown(f"Backups go to :material/folder: `{folder}`")
    clouds = setup_checks.cloud_folders()
    if clouds:
        st.caption("Keep them in a cloud folder so they survive a lost or broken computer:")
        cols = st.columns(len(clouds) + 1)
        for col, (name, path) in zip(cols, clouds.items()):
            if col.button(f"Use {name}", key=f"backup_cloud_{name}", icon=":material/cloud:", disabled=path == folder):
                setup_checks.set_backups_dir(path)
                st.rerun()
    with st.form("backup_folder_form", border=False):
        a, b = st.columns([4, 1], vertical_alignment="bottom")
        typed = a.text_input("Or another folder", placeholder=str(Path.home() / "Backups" / "Venato"),
                             help="The whole path to a folder. It's created if needed.")
        if b.form_submit_button("Use this folder"):
            try:
                setup_checks.set_backups_dir(typed)
                st.rerun()
            except ValueError as e:
                st.error(str(e))
    if folder != setup_checks.default_backups_dir():
        if st.button("Back to the default folder", key="backup_default", icon=":material/undo:"):
            setup_checks.set_backups_dir(None)
            st.rerun()


def _csv_section(name, slug, load, save, required, columns):
    """Export / import for to-dos or goals: their own CSV, one row per item."""
    st.subheader(name, anchor=False)
    st.write(f"{name} export and import as their own CSV, one row per item.")
    st.download_button(f"Download {name.lower()} CSV", load().to_csv(index=False),
                       file_name=f"venato_{slug}_{store.local_today()}.csv", mime="text/csv", icon=":material/download:")
    st.write(f"To import, use the same columns: {columns} A row whose `id` already exists updates it.")
    uploaded = st.file_uploader(f"{name} CSV file", type="csv", key=f"{slug}_csv")
    mode = st.radio(f"{name} import mode", ["Merge (update matching ids)", f"Replace all existing {name.lower()}"],
                    key=f"{slug}_mode")
    if uploaded and st.button(f"Import {name.lower()}", icon=":material/upload:"):
        new = pd.read_csv(uploaded)
        if not set(required) <= set(new.columns):
            st.error("The CSV needs " + ", ".join(f"`{c}`" for c in required) + " columns.")
        else:
            undo.checkpoint(f"Imported {name.lower()}" + (" (replacing them all)" if mode.startswith("Replace") else ""))
            count = save(new, replace=mode.startswith("Replace"))
            st.success(f"Imported {count} {name.lower()}.")
