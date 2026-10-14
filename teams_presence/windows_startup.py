"""Start-at-login support on Windows through the per-user ``Run`` registry key."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

assert sys.platform == "win32"

import winreg  # noqa: E402 - Windows only, after the platform guard for mypy

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "TeamsPresence"


def current_program() -> list[str]:
    """The command that starts this copy of the app without a console window.

    A PyInstaller build is its own windowed executable; from a source checkout
    ``pythonw.exe`` runs the package without opening a console.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable]
    interpreter = Path(sys.executable)
    windowed = interpreter.with_name("pythonw.exe")
    return [str(windowed if windowed.is_file() else interpreter), "-m", "teams_presence"]


def render_command(program: Sequence[str]) -> str:
    return subprocess.list2cmdline(list(program))


class RunKeyStartup:
    def __init__(
        self, program: Sequence[str], key_path: str = RUN_KEY, value_name: str = VALUE_NAME
    ) -> None:
        self._command = render_command(program)
        self._key_path = key_path
        self._value_name = value_name

    def _current(self) -> str | None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self._key_path) as key:
                value, kind = winreg.QueryValueEx(key, self._value_name)
        except FileNotFoundError:
            return None
        return value if kind in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) else ""

    def is_installed(self) -> bool:
        return self._current() is not None

    def install(self) -> None:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, self._key_path) as key:
            winreg.SetValueEx(key, self._value_name, 0, winreg.REG_SZ, self._command)

    def uninstall(self) -> None:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, self._key_path, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.DeleteValue(key, self._value_name)
        except FileNotFoundError:
            pass

    def refresh(self) -> bool:
        """Point an existing value at this copy of the app; return whether it was rewritten."""
        current = self._current()
        if current is None or current == self._command:
            return False
        self.install()
        return True
