"""Presence values reported by Microsoft Teams and how they are presented.

``IN_CALL`` is not a Teams availability: the monitor derives it from call windows.
"""

from __future__ import annotations

from enum import Enum


class Presence(Enum):
    AVAILABLE = "available"
    BUSY = "busy"
    IN_CALL = "in_call"
    DO_NOT_DISTURB = "do_not_disturb"
    BE_RIGHT_BACK = "be_right_back"
    AWAY = "away"
    OFFLINE = "offline"
    UNKNOWN = "unknown"

    @property
    def ha_state(self) -> str:
        return self.value

    @property
    def emoji(self) -> str:
        return _EMOJI[self]

    @property
    def label(self) -> str:
        return _LABEL[self]

    @classmethod
    def from_teams(cls, raw: str) -> Presence:
        """Map a Teams availability string (e.g. ``DoNotDisturb``) to a presence."""
        return _TEAMS_VALUES.get(raw.strip().lower(), cls.UNKNOWN)


HA_OPTIONS: tuple[str, ...] = tuple(presence.ha_state for presence in Presence)

_TEAMS_VALUES = {
    "available": Presence.AVAILABLE,
    "busy": Presence.BUSY,
    "donotdisturb": Presence.DO_NOT_DISTURB,
    "berightback": Presence.BE_RIGHT_BACK,
    "away": Presence.AWAY,
    "offline": Presence.OFFLINE,
}

_EMOJI = {
    Presence.AVAILABLE: "🟢",
    Presence.BUSY: "🔴",
    Presence.IN_CALL: "📞",
    Presence.DO_NOT_DISTURB: "⛔",
    Presence.BE_RIGHT_BACK: "🟡",
    Presence.AWAY: "🟡",
    Presence.OFFLINE: "⚫",
    Presence.UNKNOWN: "⚪",
}

_LABEL = {
    Presence.AVAILABLE: "Disponibile",
    Presence.BUSY: "Occupato",
    Presence.IN_CALL: "In chiamata",
    Presence.DO_NOT_DISTURB: "Non disturbare",
    Presence.BE_RIGHT_BACK: "Torno subito",
    Presence.AWAY: "Assente",
    Presence.OFFLINE: "Offline",
    Presence.UNKNOWN: "Sconosciuto",
}
