import pytest

from teams_presence.presence import HA_OPTIONS, Presence


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Available", Presence.AVAILABLE),
        ("Busy", Presence.BUSY),
        ("DoNotDisturb", Presence.DO_NOT_DISTURB),
        ("BeRightBack", Presence.BE_RIGHT_BACK),
        ("Away", Presence.AWAY),
        ("Offline", Presence.OFFLINE),
        (" busy ", Presence.BUSY),
        ("Presenting", Presence.UNKNOWN),
        ("", Presence.UNKNOWN),
    ],
)
def test_from_teams(raw: str, expected: Presence) -> None:
    assert Presence.from_teams(raw) is expected


def test_ha_options_are_snake_case_in_order() -> None:
    assert HA_OPTIONS == (
        "available",
        "busy",
        "do_not_disturb",
        "be_right_back",
        "away",
        "offline",
        "unknown",
    )


def test_every_presence_has_emoji_and_label() -> None:
    for presence in Presence:
        assert presence.emoji
        assert presence.label
    assert Presence.BUSY.emoji == "🔴"
    assert Presence.BUSY.label == "Occupato"
    assert Presence.UNKNOWN.emoji == "⚪"
