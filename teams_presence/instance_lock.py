"""Prevent two copies of the app from running at the same time."""

from __future__ import annotations

import fcntl
from pathlib import Path
from typing import TextIO


class AlreadyRunningError(Exception):
    pass


def acquire_lock(path: Path) -> TextIO:
    """Take an exclusive lock on ``path``; keep the returned handle open while running."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise AlreadyRunningError(str(path)) from exc
    return handle
