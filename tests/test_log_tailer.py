import os
from pathlib import Path

import pytest
from logsamples import noise, user_action

from teams_presence import log_tailer
from teams_presence.log_parser import parse_line
from teams_presence.log_tailer import LogTailer, TailerStatus


def append(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)


def lines(*items: str) -> str:
    return "".join(f"{item}\n" for item in items)


def raws(tailer_lines: list[str]) -> list[str]:
    events = [parse_line(line) for line in tailer_lines]
    return [event.raw for event in events if event is not None]


@pytest.fixture
def log(tmp_path: Path) -> Path:
    return tmp_path / "MSTeams_2026-10-12_08-00-00.00.log"


def test_poll_returns_only_new_complete_lines(log: Path) -> None:
    append(log, lines("a", "b"))
    tailer = LogTailer(log.parent)
    assert tailer.poll() == ["a", "b"]
    assert tailer.poll() == []
    append(log, lines("c"))
    assert tailer.poll() == ["c"]
    assert tailer.status is TailerStatus.OK
    assert tailer.last_modified == os.stat(log).st_mtime


def test_partial_line_is_buffered_until_complete(log: Path) -> None:
    append(log, "first\npar")
    tailer = LogTailer(log.parent)
    assert tailer.poll() == ["first"]
    append(log, "tial\n")
    assert tailer.poll() == ["partial"]


def test_switches_to_newer_file(tmp_path: Path) -> None:
    old = tmp_path / "MSTeams_a.log"
    append(old, lines("old"))
    os.utime(old, (1000, 1000))
    tailer = LogTailer(tmp_path)
    assert tailer.poll() == ["old"]
    new = tmp_path / "MSTeams_b.log"
    append(new, lines("new"))
    os.utime(new, (2000, 2000))
    assert tailer.poll() == ["new"]


def test_truncated_file_is_read_from_start(log: Path) -> None:
    append(log, lines("one", "two"))
    tailer = LogTailer(log.parent)
    tailer.poll()
    log.write_text("x\n", encoding="utf-8")
    assert tailer.poll() == ["x"]


def test_invalid_utf8_is_replaced(log: Path) -> None:
    log.write_bytes(b"ok \xff\xfe\n")
    assert LogTailer(log.parent).poll() == ["ok ��"]


def test_ignores_non_teams_logs(tmp_path: Path) -> None:
    (tmp_path / "TeamsSwitcher.log_2026.log").write_text("x\n", encoding="utf-8")
    tailer = LogTailer(tmp_path)
    assert tailer.poll() == []
    assert tailer.status is TailerStatus.MISSING


def test_missing_directory(tmp_path: Path) -> None:
    tailer = LogTailer(tmp_path / "absent")
    assert tailer.poll() == []
    assert tailer.status is TailerStatus.MISSING
    assert tailer.initial_backscan(parse_line) is None


def test_permission_denied(tmp_path: Path) -> None:
    locked = tmp_path / "locked"
    locked.mkdir()
    append(locked / "MSTeams_a.log", lines("x"))
    locked.chmod(0)
    try:
        tailer = LogTailer(locked)
        assert tailer.poll() == []
        assert tailer.status is TailerStatus.PERMISSION_DENIED
    finally:
        locked.chmod(0o755)


def test_backscan_finds_last_event_and_continues_from_end(log: Path) -> None:
    append(log, lines(user_action("Away"), user_action("Busy"), noise()))
    tailer = LogTailer(log.parent)
    event = tailer.initial_backscan(parse_line)
    assert event is not None
    assert event.raw == "Busy"
    assert tailer.poll() == []
    append(log, lines(user_action("Available")))
    assert raws(tailer.poll()) == ["Available"]


def test_backscan_across_chunk_boundaries(log: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(log_tailer, "CHUNK_SIZE", 64)
    append(log, lines(user_action("DoNotDisturb"), *[noise()] * 20))
    event = LogTailer(log.parent).initial_backscan(parse_line)
    assert event is not None
    assert event.raw == "DoNotDisturb"


def test_backscan_leaves_incomplete_last_line_for_next_poll(log: Path) -> None:
    busy = user_action("Busy")
    append(log, lines(user_action("Away")) + busy[:40])
    tailer = LogTailer(log.parent)
    event = tailer.initial_backscan(parse_line)
    assert event is not None
    assert event.raw == "Away"
    append(log, busy[40:] + "\n")
    assert raws(tailer.poll()) == ["Busy"]


def test_backscan_without_events(log: Path) -> None:
    append(log, lines(noise(), noise()))
    tailer = LogTailer(log.parent)
    assert tailer.initial_backscan(parse_line) is None
    assert tailer.status is TailerStatus.OK
