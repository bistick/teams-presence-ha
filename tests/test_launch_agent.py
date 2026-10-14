import plistlib
import sys
from pathlib import Path

import pytest

from teams_presence.launch_agent import LABEL, LaunchAgent, current_program, render_plist

PROGRAM = ["/venv/bin/python", "-m", "teams_presence"]
BUNDLE = ["/Applications/TeamsPresence.app/Contents/MacOS/TeamsPresence"]


def test_render_plist() -> None:
    plist = render_plist(PROGRAM, Path("/logs"))
    assert plist == {
        "Label": LABEL,
        "ProgramArguments": ["/venv/bin/python", "-m", "teams_presence"],
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "LimitLoadToSessionType": "Aqua",
        "ProcessType": "Interactive",
        "StandardOutPath": "/logs/launchd.out.log",
        "StandardErrorPath": "/logs/launchd.err.log",
    }


def test_current_program_from_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "executable", "/venv/bin/python")
    assert current_program() == PROGRAM


def test_current_program_from_bundle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", BUNDLE[0])
    assert current_program() == BUNDLE


def test_install_and_uninstall(tmp_path: Path) -> None:
    plist_path = tmp_path / "LaunchAgents" / f"{LABEL}.plist"
    agent = LaunchAgent(plist_path, PROGRAM, tmp_path / "logs")
    assert not agent.is_installed()
    agent.install()
    assert agent.is_installed()
    assert (tmp_path / "logs").is_dir()
    with plist_path.open("rb") as handle:
        assert plistlib.load(handle) == render_plist(PROGRAM, tmp_path / "logs")
    agent.uninstall()
    assert not agent.is_installed()
    agent.uninstall()  # idempotent


def test_refresh_leaves_absent_plist_absent(tmp_path: Path) -> None:
    agent = LaunchAgent(tmp_path / f"{LABEL}.plist", BUNDLE, tmp_path / "logs")
    assert agent.refresh() is False
    assert not agent.is_installed()


def test_refresh_repoints_plist_to_this_copy(tmp_path: Path) -> None:
    plist_path = tmp_path / f"{LABEL}.plist"
    LaunchAgent(plist_path, PROGRAM, tmp_path / "logs").install()
    agent = LaunchAgent(plist_path, BUNDLE, tmp_path / "logs")
    assert agent.refresh() is True
    with plist_path.open("rb") as handle:
        assert plistlib.load(handle)["ProgramArguments"] == BUNDLE
    assert agent.refresh() is False  # already current


def test_refresh_rewrites_unreadable_plist(tmp_path: Path) -> None:
    plist_path = tmp_path / f"{LABEL}.plist"
    plist_path.write_bytes(b"not a plist")
    agent = LaunchAgent(plist_path, BUNDLE, tmp_path / "logs")
    assert agent.refresh() is True
    with plist_path.open("rb") as handle:
        assert plistlib.load(handle) == render_plist(BUNDLE, tmp_path / "logs")
