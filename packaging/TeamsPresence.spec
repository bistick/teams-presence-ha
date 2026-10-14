# PyInstaller spec for the TeamsPresence.app menu bar bundle.
# Build from the repository root: pyinstaller --noconfirm packaging/TeamsPresence.spec
import os
from importlib.metadata import version

from PyInstaller.utils.hooks import copy_metadata

VERSION = version("teams-presence")

a = Analysis(
    [os.path.join(SPECPATH, "launcher.py")],
    pathex=[os.path.dirname(SPECPATH)],
    # keyring discovers its backends through entry points, which live in the dist metadata.
    datas=copy_metadata("keyring"),
    hiddenimports=["keyring.backends.macOS"],
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
)
coll = COLLECT(exe, a.binaries, a.datas, name="TeamsPresence")
app = BUNDLE(
    coll,
    name="TeamsPresence.app",
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
