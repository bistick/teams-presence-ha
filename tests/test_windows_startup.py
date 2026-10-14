import contextlib
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

if sys.platform != "win32":
    pytest.skip("Windows registry only", allow_module_level=True)

import winreg

from teams_presence.windows_startup import RunKeyStartup, current_program, render_command

SOURCE = [r"C:\venv\Scripts\pythonw.exe", "-m", "teams_presence"]
FROZEN = [r"C:\Program Files\TeamsPresence\TeamsPresence.exe"]


@pytest.fixture
def key_path() -> Iterator[str]:
    """A throwaway HKCU key standing in for the real Run key."""
    path = rf"Software\TeamsPresenceTests\{uuid.uuid4().hex}"
    yield path
    for name in (path, r"Software\TeamsPresenceTests"):
        with contextlib.suppress(OSError):
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, name)


def read_value(key_path: str) -> str:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        value, _kind = winreg.QueryValueEx(key, "TeamsPresence")
    return str(value)


def test_render_command_quotes_paths_with_spaces() -> None:
    assert render_command(FROZEN) == r'"C:\Program Files\TeamsPresence\TeamsPresence.exe"'


def test_current_program_from_source_prefers_pythonw(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "python.exe").touch()
    (tmp_path / "pythonw.exe").touch()
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python.exe"))
    assert current_program() == [str(tmp_path / "pythonw.exe"), "-m", "teams_presence"]


def test_current_program_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", FROZEN[0])
    assert current_program() == FROZEN


def test_install_and_uninstall(key_path: str) -> None:
    startup = RunKeyStartup(FROZEN, key_path=key_path)
    assert not startup.is_installed()
    startup.install()
    assert startup.is_installed()
    assert read_value(key_path) == render_command(FROZEN)
    startup.uninstall()
    assert not startup.is_installed()
    startup.uninstall()  # idempotent


def test_refresh_leaves_absent_value_absent(key_path: str) -> None:
    startup = RunKeyStartup(FROZEN, key_path=key_path)
    assert startup.refresh() is False
    assert not startup.is_installed()


def test_refresh_repoints_value_to_this_copy(key_path: str) -> None:
    RunKeyStartup(SOURCE, key_path=key_path).install()
    startup = RunKeyStartup(FROZEN, key_path=key_path)
    assert startup.refresh() is True
    assert read_value(key_path) == render_command(FROZEN)
    assert startup.refresh() is False  # already current
