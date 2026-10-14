"""Start-at-login support through a per-user LaunchAgent.

launchd loads ``~/Library/LaunchAgents`` at login, so installing only writes the plist:
``launchctl bootstrap`` would start a duplicate instance now, and ``bootout`` from an
instance launchd started would terminate the app itself.
"""

from __future__ import annotations

import plistlib
import sys
from collections.abc import Sequence
from pathlib import Path

LABEL = "it.denami.teams-presence"


def default_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def current_program() -> list[str]:
    """The command that starts this copy of the app.

    In a PyInstaller ``.app`` bundle ``sys.executable`` is the bundle's own executable;
    from a source checkout it is the interpreter, which needs ``-m teams_presence``.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "teams_presence"]


def render_plist(program: Sequence[str], log_dir: Path) -> dict[str, object]:
    return {
        "Label": LABEL,
        "ProgramArguments": list(program),
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "LimitLoadToSessionType": "Aqua",
        "ProcessType": "Interactive",
        "StandardOutPath": str(log_dir / "launchd.out.log"),
        "StandardErrorPath": str(log_dir / "launchd.err.log"),
    }


class LaunchAgent:
    def __init__(self, plist_path: Path, program: Sequence[str], log_dir: Path) -> None:
        self._plist_path = plist_path
        self._program = list(program)
        self._log_dir = log_dir

    def is_installed(self) -> bool:
        return self._plist_path.is_file()

    def install(self) -> None:
        self._plist_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        with self._plist_path.open("wb") as handle:
            plistlib.dump(render_plist(self._program, self._log_dir), handle)

    def uninstall(self) -> None:
        self._plist_path.unlink(missing_ok=True)

    def refresh(self) -> bool:
        """Point an installed plist at this copy of the app; return whether it was rewritten.

        Keeps start-at-login working after switching from a source checkout to the
        ``.app`` bundle, or after the bundle moved. An absent plist stays absent.
        """
        if not self.is_installed():
            return False
        try:
            with self._plist_path.open("rb") as handle:
                current = plistlib.load(handle)
        except (OSError, plistlib.InvalidFileException):
            current = None
        if current == render_plist(self._program, self._log_dir):
            return False
        self.install()
        return True
