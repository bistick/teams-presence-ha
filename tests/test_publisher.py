import time
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone

import pytest

from teams_presence.ha_client import HAError, HAErrorKind
from teams_presence.presence import HA_OPTIONS, Presence
from teams_presence.publisher import (
    HEARTBEAT_SECONDS,
    Payload,
    Publisher,
    build_payload,
    make_sender,
)

TZ = timezone(timedelta(hours=2))


class Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class FakeSend:
    def __init__(self) -> None:
        self.calls: list[tuple[Payload, float]] = []
        self.errors: list[HAError] = []

    def __call__(self, payload: Payload, timeout: float) -> None:
        self.calls.append((payload, timeout))
        if self.errors:
            raise self.errors.pop(0)


def payload(state: str = "busy") -> Payload:
    return Payload(state=state, attributes={})


def unreachable() -> HAError:
    return HAError(HAErrorKind.UNREACHABLE, "down")


def test_build_payload() -> None:
    since = datetime(2026, 10, 12, 16, 36, 4, 789253, tzinfo=TZ)
    built = build_payload(Presence.BUSY, "Busy", since)
    assert built.state == "busy"
    assert built.attributes == {
        "friendly_name": "Teams status",
        "icon": "mdi:microsoft-teams",
        "device_class": "enum",
        "options": list(HA_OPTIONS),
        "teams_availability": "Busy",
        "last_change": "2026-10-12T16:36:04+02:00",
        "source": "teams-log",
    }


def test_make_sender_adds_last_seen() -> None:
    received: list[tuple[str, Mapping[str, object], float | None]] = []

    class FakeClient:
        def publish(
            self, state: str, attributes: Mapping[str, object], timeout: float | None = None
        ) -> None:
            received.append((state, attributes, timeout))

    send = make_sender(
        lambda: FakeClient(), now=lambda: datetime(2026, 10, 12, 16, 41, 4, tzinfo=TZ)
    )
    send(Payload("busy", {"a": 1}), 5.0)
    assert received == [("busy", {"a": 1, "last_seen": "2026-10-12T16:41:04+02:00"}, 5.0)]


def test_make_sender_without_client_is_not_configured() -> None:
    with pytest.raises(HAError) as info:
        make_sender(lambda: None)(payload(), 5.0)
    assert info.value.kind is HAErrorKind.NOT_CONFIGURED


def test_step_without_pending_waits_for_submit() -> None:
    send = FakeSend()
    assert Publisher(send, Clock()).step() is None
    assert send.calls == []


def test_successful_send_records_result() -> None:
    send = FakeSend()
    publisher = Publisher(send, Clock())
    publisher.submit(payload())
    assert publisher.step() is None
    assert send.calls == [(payload(), 5.0)]
    result = publisher.last_result
    assert result is not None
    assert result.ok
    assert result.at == 1000.0


def test_latest_submission_wins() -> None:
    send = FakeSend()
    publisher = Publisher(send, Clock())
    publisher.submit(payload("busy"))
    publisher.submit(payload("away"))
    publisher.step()
    assert send.calls == [(payload("away"), 5.0)]


def test_backoff_schedule() -> None:
    send = FakeSend()
    send.errors = [unreachable() for _ in range(5)]
    clock = Clock()
    publisher = Publisher(send, clock)
    publisher.submit(payload())
    delays = []
    for _ in range(5):
        delay = publisher.step()
        assert delay is not None
        delays.append(delay)
        clock.now += delay
    assert delays == [5.0, 15.0, 60.0, 60.0, 60.0]
    result = publisher.last_result
    assert result is not None
    assert not result.ok
    assert result.error is not None
    assert result.error.kind is HAErrorKind.UNREACHABLE


def test_step_before_due_returns_remaining_wait() -> None:
    send = FakeSend()
    send.errors = [unreachable()]
    clock = Clock()
    publisher = Publisher(send, clock)
    publisher.submit(payload())
    publisher.step()
    clock.now += 2.0
    assert publisher.step() == 3.0
    assert len(send.calls) == 1


def test_unauthorized_retries_every_minute() -> None:
    send = FakeSend()
    send.errors = [HAError(HAErrorKind.UNAUTHORIZED, "HTTP 401", 401) for _ in range(2)]
    clock = Clock()
    publisher = Publisher(send, clock)
    publisher.submit(payload())
    first = publisher.step()
    assert first == 60.0
    clock.now += first
    assert publisher.step() == 60.0


def test_new_submission_resets_backoff() -> None:
    send = FakeSend()
    send.errors = [unreachable()]
    publisher = Publisher(send, Clock())
    publisher.submit(payload("busy"))
    assert publisher.step() == 5.0
    publisher.submit(payload("away"))
    assert publisher.step() is None
    assert send.calls[-1] == (payload("away"), 5.0)


def test_heartbeat_due() -> None:
    clock = Clock()
    publisher = Publisher(FakeSend(), clock)
    assert publisher.heartbeat_due()
    publisher.submit(payload())
    assert not publisher.heartbeat_due()
    publisher.step()
    assert not publisher.heartbeat_due()
    clock.now += HEARTBEAT_SECONDS - 1
    assert not publisher.heartbeat_due()
    clock.now += 1
    assert publisher.heartbeat_due()


def test_stop_sends_final_payload_with_short_timeout() -> None:
    send = FakeSend()
    publisher = Publisher(send, Clock())
    publisher.start()
    publisher.stop(final=payload("unknown"))
    assert send.calls[-1] == (payload("unknown"), 2.0)


def test_stop_is_idempotent() -> None:
    send = FakeSend()
    publisher = Publisher(send, Clock())
    publisher.start()
    publisher.stop(final=payload("unknown"))
    publisher.stop(final=payload("unknown"))
    assert send.calls == [(payload("unknown"), 2.0)]


def test_stop_swallows_final_error() -> None:
    send = FakeSend()
    send.errors = [unreachable()]
    publisher = Publisher(send, Clock())
    publisher.stop(final=payload("unknown"))
    assert len(send.calls) == 1


def test_worker_thread_delivers_submission() -> None:
    send = FakeSend()
    publisher = Publisher(send)
    publisher.start()
    publisher.submit(payload())
    deadline = time.monotonic() + 2.0
    while not send.calls and time.monotonic() < deadline:
        time.sleep(0.01)
    publisher.stop()
    assert send.calls == [(payload(), 5.0)]
