from datetime import datetime, timedelta, timezone

import pytest
from logsamples import (
    CALL_WINDOW,
    call_end,
    call_start,
    close_prompt,
    cloud_state,
    global_state,
    icon_update,
    noise,
    user_action,
    window_destroyed,
)

from teams_presence.log_parser import CallEvent, PresenceEvent, Signal, parse_line
from teams_presence.presence import Presence

_EXPECTED_TS = datetime(2026, 10, 12, 16, 36, 4, 789253, tzinfo=timezone(timedelta(hours=2)))


@pytest.mark.parametrize(
    ("line", "signal"),
    [
        (user_action("Busy"), Signal.USER_ACTION),
        (icon_update("Busy"), Signal.ICON_UPDATE),
        (global_state("Busy"), Signal.GLOBAL_STATE),
    ],
)
def test_parses_each_signal(line: str, signal: Signal) -> None:
    assert parse_line(line) == PresenceEvent(
        timestamp=_EXPECTED_TS, raw="Busy", presence=Presence.BUSY, signal=signal
    )


def test_unrecognised_value_is_unknown_and_keeps_raw() -> None:
    event = parse_line(user_action("Presenting"))
    assert isinstance(event, PresenceEvent)
    assert event.presence is Presence.UNKNOWN
    assert event.raw == "Presenting"


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (
            user_action("Busy").replace("availability: Busy", "availability:DoNotDisturb"),
            "DoNotDisturb",
        ),
        (user_action("Busy").replace("availability: Busy", "availability:  Away"), "Away"),
        (icon_update("Busy").replace("v2: Busy", "v2:Available"), "Available"),
    ],
)
def test_tolerates_spacing_variations(line: str, expected: str) -> None:
    event = parse_line(line)
    assert isinstance(event, PresenceEvent)
    assert event.raw == expected


@pytest.mark.parametrize(
    "line",
    [
        noise(),
        cloud_state("Busy"),
        close_prompt("send"),
        close_prompt("std::nullopt"),
        "",
        "garbage",
        user_action("Busy").split(" ", 1)[1],  # no timestamp
        "2026-13-45T99:99:99+02:00 x UserPresenceAction: {availability: Busy}",
    ],
)
def test_ignores_irrelevant_or_malformed_lines(line: str) -> None:
    assert parse_line(line) is None


@pytest.mark.parametrize(
    ("line", "active"),
    [
        (call_start(), True),
        (call_end(), False),
        (window_destroyed(), False),
    ],
)
def test_parses_call_window_events(line: str, active: bool) -> None:
    assert parse_line(line) == CallEvent(timestamp=_EXPECTED_TS, window=CALL_WINDOW, active=active)


def test_call_events_keep_the_window_name() -> None:
    event = parse_line(call_start(window="other").replace("tags=)", "tags=Main)"))
    assert event == CallEvent(timestamp=_EXPECTED_TS, window="other", active=True)
