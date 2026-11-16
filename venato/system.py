"""
Everything that differs between macOS, Windows and Linux, in one place:
where the data folder is, how to open a folder, and what things are called.
No Streamlit, so store.py and the scripts can use it.
"""

import os
import subprocess
import sys
from pathlib import Path

import keyring
from keyring.errors import KeyringError

IS_MAC = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"

OLD_NAME = "Arete"                # the app's first name (ARETE_ environment variables still work)
OLD_NAMES = ("Veneto", "Arete")   # earlier names, newest first: data and saved keys come across from them
SECRET_SERVICE = "Venato"
SECRET_ACCOUNTS = ("anthropic-api-key", "partner-ics-url", "outlook-ics-url", "strava-app", "strava-tokens")


def default_data_dir(name="Venato"):
    """Where Venato keeps the user's data, following each system's convention."""
    if IS_MAC:
        return Path.home() / "Library" / "Application Support" / name
    if IS_WINDOWS:
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / name
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / name


def env(name, default=None):
    """An environment variable VENATO_<name>, or the older ARETE_<name> (from before the rename)."""
    return os.environ.get(f"VENATO_{name}") or os.environ.get(f"{OLD_NAME.upper()}_{name}") or default


def data_dir():
    """The data folder: $VENATO_DATA_DIR, else the standard place. The first time Venato runs on a
    computer that had it under an earlier name (Veneto, Arete), that data folder is copied across
    (the old one is left as it was, as a backup)."""
    chosen = env("DATA_DIR")
    if chosen:
        return Path(chosen)
    new = default_data_dir()
    if not new.exists():
        old = next((d for d in map(default_data_dir, OLD_NAMES) if d.is_dir()), None)
        if old:
            import shutil
            try:
                shutil.copytree(old, new)
            except OSError:
                return old                # couldn't copy: keep using the old folder rather than lose anything
    return new


def _move_old_secrets():
    """Copy saved keys and links from the earlier names to Venato's (never over one already there).
    The old copies stay, so an older version of the app still finds them."""
    for old in OLD_NAMES:
        for account in SECRET_ACCOUNTS:
            try:
                secret = keyring.get_password(old, account)
                if not secret:
                    continue
                if not keyring.get_password(SECRET_SERVICE, account):
                    keyring.set_password(SECRET_SERVICE, account, secret)
            except KeyringError:
                pass


_migrated = False


def migrate_from_old_name():
    """Bring an install from an earlier name across: its saved keys and links, and (through
    data_dir) its data folder. Once per run; not for tests or the demo (VENATO_DATA_DIR set)."""
    global _migrated
    if _migrated or env("DATA_DIR"):
        return
    _migrated = True
    _move_old_secrets()
    data_dir()


def open_folder(path):
    """Show a folder in Finder / File Explorer / the file manager (creating it if needed)."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    if IS_WINDOWS:
        os.startfile(path)  # noqa: S606 - opens the folder in File Explorer
    else:
        subprocess.run(["open" if IS_MAC else "xdg-open", str(path)], check=False)


# Words for the UI, so messages match the computer they're shown on.
COMPUTER = "Mac" if IS_MAC else "PC" if IS_WINDOWS else "computer"
FILE_MANAGER = "Finder" if IS_MAC else "File Explorer" if IS_WINDOWS else "your file manager"
SECRET_STORE = ("macOS Keychain" if IS_MAC else "Windows Credential Manager" if IS_WINDOWS
                else "system keyring")


# ---------------------------------------------------------------------------
# Desktop notifications
# ---------------------------------------------------------------------------

# Windows: a toast through PowerShell (built in), shown as from PowerShell so no app
# registration is needed. The text comes in through environment variables, never
# pasted into the script, so nothing in a block's name can run as code.
_WINDOWS_TOAST = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$text = $xml.GetElementsByTagName('text')
$text.Item(0).AppendChild($xml.CreateTextNode($env:VENATO_TITLE)) > $null
$text.Item(1).AppendChild($xml.CreateTextNode($env:VENATO_BODY)) > $null
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($xml))
"""


def notification_command(title, body):
    """(argv, extra environment) that shows a notification on this system, or None if there's no way."""
    if IS_MAC:
        # The text goes in as arguments (argv), not into the AppleScript itself.
        return (["osascript", "-e", "on run argv", "-e",
                 "display notification (item 2 of argv) with title (item 1 of argv)",
                 "-e", "end run", title, body], {})
    if IS_WINDOWS:
        return (["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-Command", _WINDOWS_TOAST], {"VENATO_TITLE": title, "VENATO_BODY": body})
    import shutil
    if shutil.which("notify-send"):
        return (["notify-send", "--app-name=Venato", title, body], {})
    return None


def notify(title, body=""):
    """Show a desktop notification; True if it was handed to the system."""
    cmd = notification_command(str(title), str(body))
    if not cmd:
        return False
    argv, env = cmd
    flags = subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0   # no console window flashing up
    try:
        done = subprocess.run(argv, env={**os.environ, **env}, capture_output=True, timeout=30,
                              creationflags=flags, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0
