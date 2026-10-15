from collections.abc import Callable

from logsamples import call_end, call_start, global_state, icon_update, noise, user_action

from teams_presence.log_parser import PresenceEvent, parse_line
from teams_presence.log_tailer import TailerStatus
from teams_presence.monitor import STALE_AFTER_SECONDS, PresenceMonitor, SourceStatus
from teams_presence.presence import Presence

# Well past the epoch: Windows cannot convert timestamps near 0 to local time.
T0 = 1_700_000_000.0


class FakeTailer:
    def __init__(self, *backscan_lines: str) -> None:
        self.status = TailerStatus.OK
        self.last_modified: float | None = T0
        self.lines: list[str] = []
        self._backscan_lines = backscan_lines

    def poll(self) -> list[str]:
        lines, self.lines = self.lines, []
        return lines

    def initial_backscan[T](self, parse: Callable[[str], T | None]) -> T | None:
        for line in reversed(self._backscan_lines):
            item = parse(line)
            if item is not None:
                return item
        return None


class Clock:
    def __init__(self, now: float = T0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def event(line: str) -> PresenceEvent:
    parsed = parse_line(line)
    assert isinstance(parsed, PresenceEvent)
    return parsed


def test_first_tick_uses_backscan_event() -> None:
    busy = event(user_action("Busy"))
    monitor = PresenceMonitor(FakeTailer(user_action("Busy")), lambda: True, Clock())
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
    first_line = user_action("Busy", ts="2026-10-12T10:00:00+02:00")
    first = event(first_line)
    tailer = FakeTailer(first_line)
    monitor = PresenceMonitor(tailer, lambda: True, Clock())
    monitor.tick()
    tailer.lines = [global_state("Busy", ts="2026-10-12T10:05:00+02:00")]
    state = monitor.tick()
    assert state.changed is False
    assert state.since == first.timestamp


def test_teams_not_running_is_offline() -> None:
    running = [True]
    monitor = PresenceMonitor(FakeTailer(user_action("Busy")), lambda: running[0], Clock())
    monitor.tick()
    running[0] = False
    state = monitor.tick()
    assert state.presence is Presence.OFFLINE
    assert state.raw is None
    assert state.source is SourceStatus.TEAMS_NOT_RUNNING
    assert state.changed
    assert state.since.timestamp() == T0


def test_stale_log_is_unknown_then_recovers() -> None:
    clock = Clock()
    tailer = FakeTailer(user_action("Busy"))
    monitor = PresenceMonitor(tailer, lambda: True, clock)
    monitor.tick()
    clock.now = T0 + STALE_AFTER_SECONDS
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
    tailer = FakeTailer(user_action("Busy"))
    monitor = PresenceMonitor(tailer, lambda: True, clock)
    monitor.tick()
    clock.now = T0 + 3600  # one hour asleep; Teams wrote nothing meanwhile
    monitor.note_wake()
    after_wake = monitor.tick()
    assert after_wake.presence is Presence.BUSY
    assert after_wake.changed is False
    clock.now += STALE_AFTER_SECONDS + 1
    assert monitor.tick().source is SourceStatus.STALE


def test_missing_logs_and_permission_denied_are_unknown() -> None:
    tailer = FakeTailer(user_action("Busy"))
    monitor = PresenceMonitor(tailer, lambda: True, Clock())
    tailer.status = TailerStatus.MISSING
    missing = monitor.tick()
    assert (missing.presence, missing.source) == (Presence.UNKNOWN, SourceStatus.LOGS_MISSING)
    tailer.status = TailerStatus.PERMISSION_DENIED
    denied = monitor.tick()
    assert (denied.presence, denied.source) == (Presence.UNKNOWN, SourceStatus.PERMISSION_DENIED)
    assert denied.changed


def test_call_window_is_in_call_until_it_closes() -> None:
    tailer = FakeTailer(user_action("Available", ts="2026-10-12T09:00:00+02:00"))
    monitor = PresenceMonitor(tailer, lambda: True, Clock())
    monitor.tick()
    start = "2026-10-12T10:00:00+02:00"
    tailer.lines = [call_start(ts=start), user_action("Busy", ts="2026-10-12T10:00:01+02:00")]
    in_call = monitor.tick()
    assert (in_call.presence, in_call.raw) == (Presence.IN_CALL, "Busy")
    assert in_call.since.isoformat() == start
    tailer.lines = [call_end(ts="2026-10-12T10:30:00+02:00")]
    ended = monitor.tick()
    assert (ended.presence, ended.raw) == (Presence.BUSY, "Busy")
    assert ended.since.isoformat() == "2026-10-12T10:30:00+02:00"
    tailer.lines = [user_action("Available", ts="2026-10-12T10:30:01+02:00")]
    assert monitor.tick().presence is Presence.AVAILABLE


def test_other_windows_closing_do_not_end_the_call() -> None:
    tailer = FakeTailer(user_action("Busy"), call_start())
    monitor = PresenceMonitor(tailer, lambda: True, Clock())
    assert monitor.tick().presence is Presence.IN_CALL
    tailer.lines = [call_end(window="chat-popout"), noise()]
    assert monitor.tick().presence is Presence.IN_CALL


def test_backscan_finds_an_open_call() -> None:
    tailer = FakeTailer(
        call_start(window="old", ts="2026-10-12T08:00:00+02:00"),
        call_end(window="old", ts="2026-10-12T08:30:00+02:00"),
        call_start(ts="2026-10-12T10:00:00+02:00"),
        user_action("Busy", ts="2026-10-12T10:00:01+02:00"),
    )
    state = PresenceMonitor(tailer, lambda: True, Clock()).tick()
    assert state.presence is Presence.IN_CALL
    assert state.since.isoformat() == "2026-10-12T10:00:00+02:00"


def test_backscan_ignores_a_closed_call() -> None:
    tailer = FakeTailer(
        user_action("Busy", ts="2026-10-12T10:00:01+02:00"),
        call_start(ts="2026-10-12T10:00:00+02:00"),
        call_end(ts="2026-10-12T10:30:00+02:00"),
    )
    state = PresenceMonitor(tailer, lambda: True, Clock()).tick()
    assert state.presence is Presence.BUSY
    assert state.since.isoformat() == "2026-10-12T10:30:00+02:00"


def test_teams_quitting_ends_the_call() -> None:
    running = [True]
    tailer = FakeTailer(user_action("Busy"), call_start())
    monitor = PresenceMonitor(tailer, lambda: running[0], Clock())
    assert monitor.tick().presence is Presence.IN_CALL
    running[0] = False
    assert monitor.tick().presence is Presence.OFFLINE
    running[0] = True
    assert monitor.tick().presence is Presence.BUSY
