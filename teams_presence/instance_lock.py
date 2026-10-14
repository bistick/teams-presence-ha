"""Prevent two copies of the app from running at the same time."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TextIO


class AlreadyRunningError(Exception):
    pass


def acquire_lock(path: Path) -> TextIO:
    """Take an exclusive lock on ``path``; keep the returned handle open while running."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a", encoding="utf-8")
    try:
        _lock(handle)
    except OSError as exc:
        handle.close()
        raise AlreadyRunningError(str(path)) from exc
    return handle


if sys.platform == "win32":
    import msvcrt

    def _lock(handle: TextIO) -> None:
        # Byte-range lock on the first byte; it may lie past the end of the empty file.
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

else:
    import fcntl

    def _lock(handle: TextIO) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
