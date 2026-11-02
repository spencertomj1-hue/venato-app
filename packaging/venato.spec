# PyInstaller recipe for the packaged app, with Python and every package inside
# (so nothing else needs installing):
#   Windows: dist/Venato/Venato.exe   -> wrapped into Venato-Setup.exe by Inno Setup (packaging/venato.iss)
#   macOS:   dist/Venato.app         -> wrapped into Venato.dmg with hdiutil
# Run on that system, from the project folder:
#   pyinstaller packaging/venato.spec --noconfirm
# The GitHub workflow .github/workflows/release.yml does all of this.
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).parent
MAC = sys.platform == "darwin"
VERSION = os.environ.get("VENATO_VERSION", "0.0.0")
# The app reads its own version from venato/VERSION (for "a new version is available").
(ROOT / "venato" / "VERSION").write_text(VERSION + "\n", encoding="utf-8")

datas = [
    (str(ROOT / "app.py"), "."),                                     # Streamlit runs it as a file
    (str(ROOT / ".streamlit" / "config.toml"), ".streamlit"),
    (str(ROOT / "assets"), "assets"),
    (str(ROOT / "venato" / "ui" / "components"), "venato/ui/components"),
    (str(ROOT / "venato" / "VERSION"), "venato"),
]
binaries = []
# app.py is a data file, so Venato's own modules are listed here, from the source files.
# (Not collect_submodules: it test-imports each module and silently drops the ones that
# can't be imported outside a running app, which is all of venato/ui.)
hiddenimports = [".".join(p.relative_to(ROOT).with_suffix("").parts)
                 for p in sorted((ROOT / "venato").rglob("*.py"))]
hiddenimports = [m.removesuffix(".__init__") for m in hiddenimports]

# Packages with data files, plugins or entry points that PyInstaller can't find by itself.
for package in ["streamlit", "plotly", "keyring", "webview", "claude_agent_sdk", "faster_whisper",
                "ctranslate2", "sounddevice", "_sounddevice_data", "icalendar", "recurring_ical_events",
                "tzdata"]:
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [str(ROOT / "desktop.py")],
    pathex=[str(ROOT)],
    datas=datas,
    binaries=binaries,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Venato",
    icon=str(ROOT / "assets" / ("Venato.icns" if MAC else "icon.ico")),
    console=False,                 # a normal windowed app; output goes to the data folder's logs/
)
coll = COLLECT(exe, a.binaries, a.datas, name="Venato")

if MAC:
    app = BUNDLE(
        coll,
        name="Venato.app",
        icon=str(ROOT / "assets" / "Venato.icns"),
        bundle_identifier="local.venato",
        version=VERSION,
        info_plist={
            "CFBundleName": "Venato",
            "CFBundleDisplayName": "Venato",
            "CFBundleShortVersionString": VERSION,
            "LSMinimumSystemVersion": "11.0",
            "NSHighResolutionCapable": True,
            "NSMicrophoneUsageDescription":
                "Venato records your voice when you click the mic in the chat bar, and transcribes it on this Mac.",
        },
    )
