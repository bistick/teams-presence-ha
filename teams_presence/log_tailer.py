"""Follow the newest Microsoft Teams log file and return newly written lines."""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from enum import Enum
from fnmatch import fnmatch
from pathlib import Path
from typing import BinaryIO

LOG_PATTERN = "MSTeams_*.log"
CHUNK_SIZE = 256 * 1024


def default_log_dir() -> Path:
    """Where the new Teams client writes its ``MSTeams_*.log`` files."""
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        base = Path(local) if local else Path.home() / "AppData" / "Local"
        return (
            base
            / "Packages"
            / "MSTeams_8wekyb3d8bbwe"
            / "LocalCache"
            / "Microsoft"
            / "MSTeams"
            / "Logs"
        )
    return (
        Path.home()
        / "Library"
        / "Group Containers"
        / "UBF8T346G9.com.microsoft.teams"
        / "Library"
        / "Application Support"
        / "Logs"
    )


DEFAULT_LOG_DIR = default_log_dir()


class TailerStatus(Enum):
    OK = "ok"
    MISSING = "missing"
    PERMISSION_DENIED = "permission_denied"


class LogTailer:
    def __init__(self, log_dir: Path) -> None:
        self._log_dir = log_dir
        self._path: Path | None = None
        self._offset = 0
        self._pending = b""
        self.status = TailerStatus.OK
        self.last_modified: float | None = None

    def poll(self) -> list[str]:
        """Return complete lines written since the previous call."""
        try:
            newest = self._newest_log()
            if newest is None:
                self.status = TailerStatus.MISSING
                return []
            if newest != self._path:
                self._path, self._offset, self._pending = newest, 0, b""
            return self._read_new(newest)
        except FileNotFoundError:
            self.status = TailerStatus.MISSING
            return []
        except PermissionError:
            self.status = TailerStatus.PERMISSION_DENIED
            return []

    def initial_backscan[T](self, parse: Callable[[str], T | None]) -> T | None:
        """Position after the last complete line of the newest log and return the last
        line, scanning backwards, for which ``parse`` returns a value."""
        try:
            newest = self._newest_log()
            if newest is None:
                self.status = TailerStatus.MISSING
                return None
            with newest.open("rb") as handle:
                size = self._mark_read(os.fstat(handle.fileno()))
                item, complete_end = _scan_backwards(handle, size, parse)
        except FileNotFoundError:
            self.status = TailerStatus.MISSING
            return None
        except PermissionError:
            self.status = TailerStatus.PERMISSION_DENIED
            return None
        self._path, self._offset, self._pending = newest, complete_end, b""
        return item

    def _newest_log(self) -> Path | None:
        best: tuple[float, str] | None = None
        with os.scandir(self._log_dir) as entries:
            for entry in entries:
                if not fnmatch(entry.name, LOG_PATTERN) or not entry.is_file():
                    continue
                try:
                    key = (entry.stat().st_mtime, entry.name)
                except FileNotFoundError:
                    continue
                if best is None or key > best:
                    best = key
        return None if best is None else self._log_dir / best[1]

    def _read_new(self, path: Path) -> list[str]:
        with path.open("rb") as handle:
            size = self._mark_read(os.fstat(handle.fileno()))
            if size < self._offset:
                self._offset, self._pending = 0, b""
            handle.seek(self._offset)
            data = handle.read(size - self._offset)
        self._offset += len(data)
        *complete, self._pending = (self._pending + data).split(b"\n")
        return [_decode(line) for line in complete]

    def _mark_read(self, stat: os.stat_result) -> int:
        self.status = TailerStatus.OK
        self.last_modified = stat.st_mtime
        return stat.st_size


def _decode(line: bytes) -> str:
    return line.decode("utf-8", errors="replace").rstrip("\r")


def _scan_backwards[T](
    handle: BinaryIO, size: int, parse: Callable[[str], T | None]
) -> tuple[T | None, int]:
    """Return the last parsed item and the offset just past the last complete line."""
    end = size
    carry = b""  # bytes of a later chunk that precede its first newline
    complete_end: int | None = None
    while end > 0:
        start = max(0, end - CHUNK_SIZE)
        handle.seek(start)
        block = handle.read(end - start) + carry
        if complete_end is None:
            last_newline = block.rfind(b"\n")
            if last_newline < 0:
                carry, end = block, start
                continue
            complete_end = start + last_newline + 1
            block = block[: last_newline + 1]
        chunk_lines = block.split(b"\n")
        carry = chunk_lines.pop(0) if start > 0 else b""
        for raw in reversed(chunk_lines):
            item = parse(_decode(raw))
            if item is not None:
                return item, complete_end
        end = start
    return None, complete_end if complete_end is not None else 0
