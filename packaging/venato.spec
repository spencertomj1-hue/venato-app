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
for package in ["streamlit", "keyring", "webview", "claude_agent_sdk", "faster_whisper",
                "ctranslate2", "sounddevice", "_sounddevice_data", "icalendar", "recurring_ical_events",
                "tzdata"]:
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h

# Streamlit uses pyarrow only to turn a table into bytes for st.dataframe (pyarrow.lib, .compute, .ipc,
# .pandas_compat). Parquet, Flight, Acero, datasets, Substrait, Gandiva, ORC and the cloud filesystems are never
# imported, so their Python modules and extension modules are left out. Four shared libraries stay even though
# nothing here calls them (libarrow_acero / _dataset / _substrait and libparquet): pyarrow's lib module is linked
# against them, so removing them would stop `import pyarrow` loading. Verified with a Linux build.
PYARROW_UNUSED = ["pyarrow.parquet", "pyarrow.flight", "pyarrow.acero", "pyarrow.dataset", "pyarrow.substrait",
                  "pyarrow.gandiva", "pyarrow.orc", "pyarrow.tests"]
PYARROW_UNUSED_MODULES = ("_parquet", "_dataset", "_acero", "_substrait", "_flight", "_gandiva", "_orc", "_s3fs",
                          "_gcsfs", "_hdfs", "_azurefs", "_pyarrow_cpp_tests")
PYARROW_UNUSED_LIBS = ("arrow_flight", "arrow_python_flight", "arrow_s3", "arrow_python_parquet_encryption",
                       "arrow_gandiva", "gandiva")


def _unused_pyarrow_binary(dest):
    parts = Path(dest.replace("\\", "/")).parts
    name = parts[-1]
    if name.removeprefix("lib").startswith(PYARROW_UNUSED_LIBS):      # also the copy PyInstaller links at the top
        return True
    return "pyarrow" in parts and name.startswith(PYARROW_UNUSED_MODULES)


a = Analysis(
    [str(ROOT / "desktop.py")],
    pathex=[str(ROOT)],
    datas=datas,
    binaries=binaries,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", *PYARROW_UNUSED],
)
a.binaries = [b for b in a.binaries if not _unused_pyarrow_binary(b[0])]
a.datas = [d for d in a.datas if not _unused_pyarrow_binary(d[0])]      # (PyInstaller lists the top-level symlinks here)
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
