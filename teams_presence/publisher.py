"""Background delivery of presence payloads to Home Assistant."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from teams_presence.ha_client import HAError, HAErrorKind
from teams_presence.presence import HA_OPTIONS, Presence

log = logging.getLogger(__name__)

BACKOFF_SECONDS = (5.0, 15.0, 60.0)
UNAUTHORIZED_RETRY_SECONDS = 60.0
HEARTBEAT_SECONDS = 300.0
SEND_TIMEOUT_SECONDS = 5.0
FINAL_SEND_TIMEOUT_SECONDS = 2.0
_UNEXPECTED_ERROR_RETRY_SECONDS = 60.0


@dataclass(frozen=True)
class Payload:
    state: str
    attributes: Mapping[str, object]


@dataclass(frozen=True)
class PublishResult:
    ok: bool
    at: float
    error: HAError | None = None


Send = Callable[[Payload, float], None]


class StatePublisher(Protocol):
    def publish(
        self, state: str, attributes: Mapping[str, object], timeout: float | None = None
    ) -> None: ...


def build_payload(presence: Presence, raw: str | None, since: datetime) -> Payload:
    return Payload(
        state=presence.ha_state,
        attributes={
            "friendly_name": "Teams status",
            "icon": "mdi:microsoft-teams",
            "device_class": "enum",
            "options": list(HA_OPTIONS),
            "teams_availability": raw,
            "last_change": since.isoformat(timespec="seconds"),
            "source": "teams-log",
        },
    )


def _local_now() -> datetime:
    return datetime.now().astimezone()


def make_sender(
    get_client: Callable[[], StatePublisher | None],
    now: Callable[[], datetime] = _local_now,
) -> Send:
    """Build a ``Send`` that stamps ``last_seen`` at send time on the current client."""

    def send(payload: Payload, timeout: float) -> None:
        client = get_client()
        if client is None:
            raise HAError(HAErrorKind.NOT_CONFIGURED, "Home Assistant is not configured")
        attributes = {**payload.attributes, "last_seen": now().isoformat(timespec="seconds")}
        client.publish(payload.state, attributes, timeout=timeout)

    return send


class Publisher:
    """Single-slot, latest-wins delivery queue served by one worker thread."""

    def __init__(self, send: Send, clock: Callable[[], float] = time.time) -> None:
        self._send = send
        self._clock = clock
        self._cond = threading.Condition()
        self._pending: Payload | None = None
        self._next_attempt = 0.0
        self._failures = 0
        self._last_success: float | None = None
        self._last_result: PublishResult | None = None
        self._stopping = False
        self._thread: threading.Thread | None = None

    @property
    def last_result(self) -> PublishResult | None:
        with self._cond:
            return self._last_result

    def heartbeat_due(self) -> bool:
        with self._cond:
            if self._pending is not None:
                return False
            return (
                self._last_success is None
                or self._clock() - self._last_success >= HEARTBEAT_SECONDS
            )

    def submit(self, payload: Payload) -> None:
        with self._cond:
            self._pending = payload
            self._failures = 0
            self._next_attempt = 0.0
            self._cond.notify_all()

    def step(self) -> float | None:
        """Attempt the pending send if due.

        Returns the seconds to wait before the next step, or ``None`` when there is
        nothing to send until the next ``submit``.
        """
        with self._cond:
            payload = self._pending
            if payload is None:
                return None
            wait = self._next_attempt - self._clock()
            if wait > 0:
                return wait
        error: HAError | None = None
        try:
            self._send(payload, SEND_TIMEOUT_SECONDS)
        except HAError as exc:
            error = exc
        now = self._clock()
        with self._cond:
            self._last_result = PublishResult(ok=error is None, at=now, error=error)
            superseded = self._pending is not payload
            if error is None:
                self._last_success = now
                if superseded:
                    return 0.0
                self._pending = None
                return None
            if superseded:
                return 0.0
            log.warning("publish failed (%s): %s", error.kind.value, error)
            delay = self._retry_delay(error)
            self._failures += 1
            self._next_attempt = now + delay
            return delay

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="ha-publisher", daemon=True)
        self._thread.start()

    def stop(self, final: Payload | None = None) -> None:
        """Stop the worker, then make one best-effort send of ``final``. Later calls no-op."""
        with self._cond:
            if self._stopping:
                return
            self._stopping = True
            self._cond.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=FINAL_SEND_TIMEOUT_SECONDS)
        if final is None:
            return
        try:
            self._send(final, FINAL_SEND_TIMEOUT_SECONDS)
        except HAError as exc:
            log.warning("final publish failed (%s): %s", exc.kind.value, exc)

    def _retry_delay(self, error: HAError) -> float:
        if error.kind is HAErrorKind.UNAUTHORIZED:
            return UNAUTHORIZED_RETRY_SECONDS
        return BACKOFF_SECONDS[min(self._failures, len(BACKOFF_SECONDS) - 1)]

    def _run(self) -> None:
        while True:
            try:
                delay = self.step()
            except Exception:  # keep the worker alive whatever the sender raises
                log.exception("unexpected publisher error")
                delay = _UNEXPECTED_ERROR_RETRY_SECONDS
            with self._cond:
                if self._stopping:
                    return
                if delay is None and self._pending is not None:
                    continue  # a submit arrived between step() and this check
                if delay is None or delay > 0:
                    self._cond.wait(timeout=delay)
