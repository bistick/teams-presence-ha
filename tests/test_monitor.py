from collections.abc import Callable

from logsamples import global_state, icon_update, noise, user_action

from teams_presence.log_parser import PresenceEvent, parse_line
from teams_presence.log_tailer import TailerStatus
from teams_presence.monitor import STALE_AFTER_SECONDS, PresenceMonitor, SourceStatus
from teams_presence.presence import Presence


class FakeTailer:
    def __init__(self, backscan_event: PresenceEvent | None = None) -> None:
        self.status = TailerStatus.OK
        self.last_modified: float | None = 1000.0
        self.lines: list[str] = []
        self._backscan_event = backscan_event

    def poll(self) -> list[str]:
        lines, self.lines = self.lines, []
        return lines

    def initial_backscan(
        self, parse: Callable[[str], PresenceEvent | None]
    ) -> PresenceEvent | None:
        return self._backscan_event


class Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def event(line: str) -> PresenceEvent:
    parsed = parse_line(line)
    assert parsed is not None
    return parsed


def test_first_tick_uses_backscan_event() -> None:
    busy = event(user_action("Busy"))
    monitor = PresenceMonitor(FakeTailer(busy), lambda: True, Clock())
    state = monitor.tick()
    assert state.presence is Presence.BUSY
    assert state.raw == "Busy"
    assert state.since == busy.timestamp
    assert state.changed
    assert state.source is SourceStatus.OK
    assert monitor.tick().changed is False


def test_new_lines_update_presence_last_wins() -> None:
    tailer = FakeTailer()
    monitor = PresenceMonitor(tailer, lambda: True, Clock())
    assert monitor.tick().presence is Presence.UNKNOWN
    tailer.lines = [user_action("Away"), noise(), icon_update("Busy")]
    state = monitor.tick()
    assert state.presence is Presence.BUSY
    assert state.changed


def test_repeated_presence_is_not_a_change() -> None:
    first = event(user_action("Busy", ts="2026-10-12T10:00:00+02:00"))
    tailer = FakeTailer(first)
    monitor = PresenceMonitor(tailer, lambda: True, Clock())
    monitor.tick()
    tailer.lines = [global_state("Busy", ts="2026-10-12T10:05:00+02:00")]
    state = monitor.tick()
    assert state.changed is False
    assert state.since == first.timestamp


def test_teams_not_running_is_offline() -> None:
    running = [True]
    monitor = PresenceMonitor(FakeTailer(event(user_action("Busy"))), lambda: running[0], Clock())
    monitor.tick()
    running[0] = False
    state = monitor.tick()
    assert state.presence is Presence.OFFLINE
    assert state.raw is None
    assert state.source is SourceStatus.TEAMS_NOT_RUNNING
    assert state.changed
    assert state.since.timestamp() == 1000.0


def test_stale_log_is_unknown_then_recovers() -> None:
    clock = Clock()
    tailer = FakeTailer(event(user_action("Busy")))
    monitor = PresenceMonitor(tailer, lambda: True, clock)
    monitor.tick()
    clock.now = 1000.0 + STALE_AFTER_SECONDS
    assert monitor.tick().presence is Presence.BUSY
    clock.now += 1
    stale = monitor.tick()
    assert stale.presence is Presence.UNKNOWN
    assert stale.source is SourceStatus.STALE
    tailer.last_modified = clock.now
    tailer.lines = [user_action("Available")]
    recovered = monitor.tick()
    assert recovered.presence is Presence.AVAILABLE
    assert recovered.changed


def test_wake_from_sleep_is_not_stale_until_silent_while_awake() -> None:
    clock = Clock()
    tailer = FakeTailer(event(user_action("Busy")))
    monitor = PresenceMonitor(tailer, lambda: True, clock)
    monitor.tick()
    clock.now = 1000.0 + 3600  # one hour asleep; Teams wrote nothing meanwhile
    monitor.note_wake()
    after_wake = monitor.tick()
    assert after_wake.presence is Presence.BUSY
    assert after_wake.changed is False
    clock.now += STALE_AFTER_SECONDS + 1
    assert monitor.tick().source is SourceStatus.STALE


def test_missing_logs_and_permission_denied_are_unknown() -> None:
    tailer = FakeTailer(event(user_action("Busy")))
    monitor = PresenceMonitor(tailer, lambda: True, Clock())
    tailer.status = TailerStatus.MISSING
    missing = monitor.tick()
    assert (missing.presence, missing.source) == (Presence.UNKNOWN, SourceStatus.LOGS_MISSING)
    tailer.status = TailerStatus.PERMISSION_DENIED
    denied = monitor.tick()
    assert (denied.presence, denied.source) == (Presence.UNKNOWN, SourceStatus.PERMISSION_DENIED)
    assert denied.changed
