"""Extract presence events from Microsoft Teams log lines.

The Teams log format is undocumented; every pattern lives here so a format change
stays a local fix.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from teams_presence.presence import Presence


class Signal(Enum):
    USER_ACTION = "user_action"
    ICON_UPDATE = "icon_update"
    GLOBAL_STATE = "global_state"


@dataclass(frozen=True)
class PresenceEvent:
    timestamp: datetime
    raw: str
    presence: Presence
    signal: Signal


@dataclass(frozen=True)
class CallEvent:
    """A call window opening (``active``) or closing.

    Teams keeps its availability at ``Busy`` during a call; the call shows only as a
    window that asks for confirmation before closing ("meeting" close prompt) and is
    destroyed when the call ends.
    """

    timestamp: datetime
    window: str
    active: bool


_TIMESTAMP = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))\s")
_PATTERNS = (
    (Signal.USER_ACTION, re.compile(r"UserPresenceAction: \{[^}]*?\bavailability:\s*(\w+)")),
    (Signal.ICON_UPDATE, re.compile(r"UpdateIconPresence.*?presence update to icon v\d+:\s*(\w+)")),
    (Signal.GLOBAL_STATE, re.compile(r"BroadcastGlobalState: .*?\{\s*availability:\s*(\w+)")),
)
_WINDOW = r"Window: \([^)]*?\bname=([^;)\s]+)[^)]*\)\s+"
_CALL_START = re.compile(_WINDOW + r"Setting close prompt from web: meeting\b")
_CALL_END = re.compile(
    _WINDOW + r"(?:Resetting close prompt from web|WindowCloseActionDestroy, letting)"
)


def parse_line(line: str) -> PresenceEvent | CallEvent | None:
    """Return the presence or call event carried by ``line``, or ``None`` if it carries none."""
    timestamp_match = _TIMESTAMP.match(line)
    if timestamp_match is None:
        return None
    for signal, pattern in _PATTERNS:
        match = pattern.search(line)
        if match is None:
            continue
        timestamp = _timestamp(timestamp_match)
        if timestamp is None:
            return None
        raw = match.group(1)
        return PresenceEvent(timestamp, raw, Presence.from_teams(raw), signal)
    for active, pattern in ((True, _CALL_START), (False, _CALL_END)):
        match = pattern.search(line)
        if match is None:
            continue
        timestamp = _timestamp(timestamp_match)
        if timestamp is None:
            return None
        return CallEvent(timestamp, match.group(1), active)
    return None


def _timestamp(match: re.Match[str]) -> datetime | None:
    try:
        return datetime.fromisoformat(match.group(1))
    except ValueError:
        return None
