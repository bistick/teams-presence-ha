# PyInstaller spec for Teams Presence: TeamsPresence.app on macOS, TeamsPresence.exe on Windows.
# PyInstaller does not cross-compile: build each platform on that platform.
# Build from the repository root: pyinstaller --noconfirm packaging/TeamsPresence.spec
import os
import sys
from importlib.metadata import version

from PyInstaller.utils.hooks import copy_metadata

VERSION = version("teams-presence")
IS_MACOS = sys.platform == "darwin"
# PyInstaller converts the PNG to .icns or .ico itself, through Pillow.
ICON = os.path.join(SPECPATH, "assets", "icon.png")

if IS_MACOS:
    hiddenimports = ["keyring.backends.macOS"]
else:
    # pystray picks its backend at import time, which PyInstaller cannot see.
    hiddenimports = ["keyring.backends.Windows", "win32ctypes.core", "pystray._win32"]

a = Analysis(
    [os.path.join(SPECPATH, "launcher.py")],
    pathex=[os.path.dirname(SPECPATH)],
    # keyring discovers its backends through entry points, which live in the dist metadata.
    datas=copy_metadata("keyring"),
    hiddenimports=hiddenimports,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TeamsPresence",
    console=False,
    argv_emulation=False,
    icon=ICON,
)
coll = COLLECT(exe, a.binaries, a.datas, name="TeamsPresence")

if IS_MACOS:
    app = BUNDLE(
        coll,
        name="TeamsPresence.app",
        icon=ICON,
        bundle_identifier="it.denami.teams-presence",
        version=VERSION,
        info_plist={
            "CFBundleDisplayName": "Teams Presence",
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            # Menu bar only: no Dock icon, no app switcher entry.
            "LSUIElement": True,
            "LSMinimumSystemVersion": "13.0",
            "NSHumanReadableCopyright": "Lorenzo Denami",
        },
    )
