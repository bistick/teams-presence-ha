"""Persistent settings: a JSON file for plain values, the OS credential store for the token.

The token lives in the macOS Keychain or in the Windows Credential Manager, through keyring.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlsplit

import keyring
from keyring.errors import KeyringError

APP_NAME = "TeamsPresence"
KEYRING_SERVICE = APP_NAME
KEYRING_ACCOUNT = "ha_token"
DEFAULT_ENTITY_ID = "sensor.teams_status"
_ENTITY_ID = re.compile(r"^sensor\.[a-z0-9_]+$")
_TOKEN = re.compile(r"[A-Za-z0-9._-]+")


def _windows_dir(variable: str, fallback: str) -> Path:
    value = os.environ.get(variable)
    return Path(value) if value else Path.home() / "AppData" / fallback


def app_support_dir() -> Path:
    if sys.platform == "win32":
        return _windows_dir("APPDATA", "Roaming") / APP_NAME
    return Path.home() / "Library" / "Application Support" / APP_NAME


def logs_dir() -> Path:
    if sys.platform == "win32":
        return _windows_dir("LOCALAPPDATA", "Local") / APP_NAME / "Logs"
    return Path.home() / "Library" / "Logs" / APP_NAME


@dataclass
class Config:
    ha_url: str = ""
    entity_id: str = DEFAULT_ENTITY_ID


@dataclass(frozen=True)
class LoadResult:
    config: Config
    reset: bool


class ConfigStore:
    def __init__(self, directory: Path) -> None:
        self._path = directory / "config.json"

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> LoadResult:
        """Load the config; an unreadable file is kept as ``config.json.bak`` and reset."""
        try:
            content = self._path.read_bytes()
        except FileNotFoundError:
            return LoadResult(Config(), reset=False)
        try:
            config = _parse(content.decode("utf-8"))
        except ValueError:
            self._path.replace(self._path.with_name(self._path.name + ".bak"))
            return LoadResult(Config(), reset=True)
        return LoadResult(config, reset=False)

    def save(self, config: Config) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(self._path.name + ".tmp")
        temporary.write_text(json.dumps(asdict(config), indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, self._path)


def _parse(text: str) -> Config:
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("config root must be an object")
    ha_url = data.get("ha_url", "")
    entity_id = data.get("entity_id", DEFAULT_ENTITY_ID)
    if not isinstance(ha_url, str) or not isinstance(entity_id, str):
        raise ValueError("config values must be strings")
    if ha_url and not is_valid_ha_url(ha_url):
        raise ValueError("invalid ha_url")
    if not is_valid_entity_id(entity_id):
        raise ValueError("invalid entity_id")
    return Config(ha_url=ha_url, entity_id=entity_id)


def is_valid_ha_url(url: str) -> bool:
    try:
        parts = urlsplit(url.strip())
        parts.port  # noqa: B018 - raises ValueError for a malformed or out-of-range port
    except ValueError:
        return False
    return (
        parts.scheme in ("http", "https")
        and bool(parts.hostname)
        and parts.path in ("", "/")
        and not parts.query
        and not parts.fragment
    )


def normalize_ha_url(url: str) -> str:
    return url.strip().rstrip("/")


def is_valid_entity_id(entity_id: str) -> bool:
    return _ENTITY_ID.fullmatch(entity_id) is not None


def is_valid_token(token: str) -> bool:
    """Home Assistant long-lived tokens are JWTs: no whitespace or control characters."""
    return _TOKEN.fullmatch(token.strip()) is not None


def load_token() -> str | None:
    try:
        token = keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
    except KeyringError:
        return None
    return token if isinstance(token, str) and token else None


def save_token(token: str) -> None:
    """Store the stripped token; raise ``ValueError`` (without echoing it) if invalid."""
    if not is_valid_token(token):
        raise ValueError("invalid Home Assistant token")
    keyring.set_password(KEYRING_SERVICE, KEYRING_ACCOUNT, token.strip())
