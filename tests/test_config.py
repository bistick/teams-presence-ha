from collections.abc import Iterator
from pathlib import Path

import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError

from teams_presence.config import (
    DEFAULT_ENTITY_ID,
    KEYRING_ACCOUNT,
    KEYRING_SERVICE,
    Config,
    ConfigStore,
    is_valid_entity_id,
    is_valid_ha_url,
    is_valid_token,
    load_token,
    normalize_ha_url,
    save_token,
)


class MemoryKeyring(KeyringBackend):
    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__()
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if self.store.pop((service, username), None) is None:
            raise PasswordDeleteError(username)


@pytest.fixture
def memory_keyring() -> Iterator[MemoryKeyring]:
    previous = keyring.get_keyring()
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    try:
        yield backend
    finally:
        keyring.set_keyring(previous)


def test_missing_file_gives_defaults(tmp_path: Path) -> None:
    result = ConfigStore(tmp_path).load()
    assert result.config == Config(ha_url="", entity_id=DEFAULT_ENTITY_ID)
    assert result.reset is False


def test_round_trip(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "nested")
    store.save(Config(ha_url="http://ha.local:8123", entity_id="sensor.my_teams"))
    assert store.load().config == Config(ha_url="http://ha.local:8123", entity_id="sensor.my_teams")


@pytest.mark.parametrize(
    "content",
    [
        b"{not json",
        b"[1, 2]",
        b'{"entity_id": "light.kitchen"}',
        b'{"ha_url": "ftp://x"}',
        b'{"ha_url": 5}',
        b"\xff\xfe",
    ],
)
def test_corrupt_file_is_backed_up_and_reset(tmp_path: Path, content: bytes) -> None:
    store = ConfigStore(tmp_path)
    store.path.write_bytes(content)
    result = store.load()
    assert result.reset is True
    assert result.config == Config()
    assert not store.path.exists()
    assert (tmp_path / "config.json.bak").read_bytes() == content


@pytest.mark.parametrize(
    ("url", "valid"),
    [
        ("http://homeassistant.local:8123", True),
        ("https://ha.example.com/", True),
        ("  http://192.168.1.10:8123  ", True),
        ("ftp://ha.local", False),
        ("homeassistant.local:8123", False),
        ("http://", False),
        ("http://ha.local:8123/api", False),
        ("http://ha.local:8123/?x=1", False),
        ("http://homeassistant.local:812a", False),
        ("http://ha.local:99999", False),
        ("http://[::1", False),
        ("", False),
    ],
)
def test_is_valid_ha_url(url: str, valid: bool) -> None:
    assert is_valid_ha_url(url) is valid


def test_normalize_ha_url() -> None:
    assert normalize_ha_url("  https://ha.example.com/ ") == "https://ha.example.com"


@pytest.mark.parametrize(
    ("entity_id", "valid"),
    [
        ("sensor.teams_status", True),
        ("sensor.teams_2", True),
        ("sensor.Teams", False),
        ("input_text.teams", False),
        ("sensor.", False),
        ("sensor.teams status", False),
    ],
)
def test_is_valid_entity_id(entity_id: str, valid: bool) -> None:
    assert is_valid_entity_id(entity_id) is valid


def test_token_is_stored_stripped(memory_keyring: MemoryKeyring) -> None:
    save_token("  abc.def\n")
    assert memory_keyring.store[(KEYRING_SERVICE, KEYRING_ACCOUNT)] == "abc.def"
    assert load_token() == "abc.def"


@pytest.mark.parametrize(
    ("token", "valid"),
    [
        ("eyJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJ4In0.sig-_A1", True),
        ("  abc.def\n", True),
        ("", False),
        ("   ", False),
        ("abc\ndef", False),
        ("abc def", False),
        ("abc\x00def", False),
    ],
)
def test_is_valid_token(token: str, valid: bool) -> None:
    assert is_valid_token(token) is valid


@pytest.mark.parametrize("token", ["", "   ", "abc\ndef"])
def test_invalid_token_is_rejected_and_keeps_existing(
    memory_keyring: MemoryKeyring, token: str
) -> None:
    save_token("abc")
    with pytest.raises(ValueError):
        save_token(token)
    assert load_token() == "abc"
