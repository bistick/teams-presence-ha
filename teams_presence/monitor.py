"""Turn Teams log lines into a current presence, applying call, offline and staleness rules."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from teams_presence.log_parser import CallEvent, PresenceEvent, parse_line
from teams_presence.log_tailer import TailerStatus
from teams_presence.presence import Presence

STALE_AFTER_SECONDS = 12 * 60


class SourceStatus(Enum):
    OK = "ok"
    LOGS_MISSING = "logs_missing"
    PERMISSION_DENIED = "permission_denied"
    TEAMS_NOT_RUNNING = "teams_not_running"
    STALE = "stale"


@dataclass(frozen=True)
class MonitorState:
    presence: Presence
    raw: str | None
    since: datetime
    changed: bool
    source: SourceStatus


class Tailer(Protocol):
    @property
    def status(self) -> TailerStatus: ...

    @property
    def last_modified(self) -> float | None: ...

    def poll(self) -> list[str]: ...

    def initial_backscan[T](self, parse: Callable[[str], T | None]) -> T | None: ...


class PresenceMonitor:
    def __init__(
        self,
        tailer: Tailer,
        is_teams_running: Callable[[], bool],
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._tailer = tailer
        self._is_teams_running = is_teams_running
        self._clock = clock
        self._started = False
        self._last_event: PresenceEvent | None = None
        self._calls: dict[str, datetime] = {}  # open call window -> call start
        self._call_changed_at: datetime | None = None
        self._current: tuple[Presence, str | None, SourceStatus] | None = None
        self._since: datetime | None = None
        self._awake_since: float | None = None

    def note_wake(self) -> None:
        """Record a wake from sleep: log silence while asleep does not count as stale."""
        self._awake_since = self._clock()

    def tick(self) -> MonitorState:
        self._read_events()
        now = self._clock()
        presence, raw, source, event_time = self._evaluate(now)
        key = (presence, raw, source)
        changed = key != self._current
        if changed or self._since is None:
            self._current = key
            self._since = event_time if event_time is not None else _local(now)
        return MonitorState(presence, raw, self._since, changed, source)

    def _read_events(self) -> None:
        if not self._started:
            self._started = True
            scan = _Backscan()
            self._tailer.initial_backscan(scan)
            self._last_event = scan.presence
            if scan.open_call is not None:
                self._calls[scan.open_call.window] = scan.open_call.timestamp
            self._call_changed_at = scan.call_changed_at
            return
        for line in self._tailer.poll():
            event = parse_line(line)
            if isinstance(event, PresenceEvent):
                self._last_event = event
            elif isinstance(event, CallEvent):
                self._apply_call(event)

    def _apply_call(self, event: CallEvent) -> None:
        if event.active:
            self._calls.setdefault(event.window, event.timestamp)
        elif self._calls.pop(event.window, None) is None:
            return  # a window that was not a call closed
        self._call_changed_at = event.timestamp

    def _evaluate(self, now: float) -> tuple[Presence, str | None, SourceStatus, datetime | None]:
        if not self._is_teams_running():
            self._calls.clear()  # a quitting Teams may not log its call windows closing
            return Presence.OFFLINE, None, SourceStatus.TEAMS_NOT_RUNNING, None
        if self._tailer.status is TailerStatus.MISSING:
            return Presence.UNKNOWN, None, SourceStatus.LOGS_MISSING, None
        if self._tailer.status is TailerStatus.PERMISSION_DENIED:
            return Presence.UNKNOWN, None, SourceStatus.PERMISSION_DENIED, None
        last_activity = self._tailer.last_modified
        if last_activity is not None and self._awake_since is not None:
            last_activity = max(last_activity, self._awake_since)
        if last_activity is not None and now - last_activity > STALE_AFTER_SECONDS:
            return Presence.UNKNOWN, None, SourceStatus.STALE, None
        event = self._last_event
        raw = event.raw if event is not None else None
        if self._calls:
            return Presence.IN_CALL, raw, SourceStatus.OK, min(self._calls.values())
        if event is None:
            return Presence.UNKNOWN, None, SourceStatus.OK, None
        since = event.timestamp
        if self._call_changed_at is not None and self._call_changed_at > since:
            since = self._call_changed_at
        return event.presence, event.raw, SourceStatus.OK, since


class _Backscan:
    """Parser for ``initial_backscan``: collects, scanning backwards, the last presence
    event and the most recent call window, open or closed."""

    def __init__(self) -> None:
        self.presence: PresenceEvent | None = None
        self.open_call: CallEvent | None = None
        self.call_changed_at: datetime | None = None
        self._call_resolved = False
        self._closed: dict[str, datetime] = {}  # window -> when it last closed

    def __call__(self, line: str) -> bool | None:
        event = parse_line(line)
        if isinstance(event, PresenceEvent):
            if self.presence is None:
                self.presence = event
        elif isinstance(event, CallEvent) and not self._call_resolved:
            if not event.active:
                self._closed.setdefault(event.window, event.timestamp)
            else:
                self._call_resolved = True
                closed_at = self._closed.get(event.window)
                if closed_at is None:
                    self.open_call = event
                self.call_changed_at = closed_at if closed_at is not None else event.timestamp
        return True if self.presence is not None and self._call_resolved else None


def _local(timestamp: float) -> datetime:
    return datetime.fromtimestamp(timestamp).astimezone()
