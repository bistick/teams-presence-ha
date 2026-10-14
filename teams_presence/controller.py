"""Platform-independent app logic shared by the macOS menu bar and the Windows tray UIs."""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from teams_presence.config import (
    ConfigStore,
    is_valid_entity_id,
    is_valid_ha_url,
    is_valid_token,
    load_token,
    normalize_ha_url,
    save_token,
)
from teams_presence.ha_client import HAError, HAErrorKind, HomeAssistantClient
from teams_presence.log_tailer import DEFAULT_LOG_DIR, LogTailer
from teams_presence.monitor import MonitorState, PresenceMonitor, SourceStatus
from teams_presence.presence import Presence
from teams_presence.publisher import Publisher, build_payload, make_sender

log = logging.getLogger(__name__)

_PERMISSION_HINT = (
    "Impostazioni di Sistema › Privacy e sicurezza"
    if sys.platform == "darwin"
    else "controlla i permessi della cartella"
)
_SOURCE_NOTES = {
    SourceStatus.LOGS_MISSING: "log di Teams non trovati",
    SourceStatus.PERMISSION_DENIED: f"accesso ai log negato: {_PERMISSION_HINT}",
    SourceStatus.TEAMS_NOT_RUNNING: "Teams non è in esecuzione",
    SourceStatus.STALE: "log di Teams fermo da oltre 12 minuti",
}
CONFIG_RESET_NOTICE = "⚠️ Configurazione non valida: ripristinati i valori predefiniti"


class Dialogs(Protocol):
    def ask(self, title: str, message: str, default: str, secure: bool = False) -> str | None:
        """Return the stripped text entered, or ``None`` if the user cancelled."""
        ...

    def alert(self, title: str, message: str) -> None: ...


class StartupItem(Protocol):
    """Start-at-login integration: a LaunchAgent on macOS, a Run registry value on Windows."""

    def is_installed(self) -> bool: ...

    def install(self) -> None: ...

    def uninstall(self) -> None: ...


def describe_error(error: HAError | None) -> str:
    if error is None:
        return "errore"
    if error.kind is HAErrorKind.UNAUTHORIZED:
        return "token non valido"
    if error.kind is HAErrorKind.UNREACHABLE:
        return "irraggiungibile"
    if error.kind is HAErrorKind.NOT_CONFIGURED:
        return "non configurato"
    return f"HTTP {error.status}"


class Controller:
    """Owns the monitor, the publisher and the settings; the UI only renders and forwards."""

    def __init__(
        self,
        store: ConfigStore,
        startup: StartupItem,
        dialogs: Dialogs,
        is_teams_running: Callable[[], bool],
    ) -> None:
        self._store = store
        loaded = store.load()
        if loaded.reset:
            log.warning("invalid config moved to %s.bak; defaults loaded", store.path)
        self.config_reset = loaded.reset
        self._config = loaded.config
        self._client = self._build_client()
        self._startup = startup
        self._dialogs = dialogs
        self._monitor = PresenceMonitor(LogTailer(DEFAULT_LOG_DIR), is_teams_running)
        self._publisher = Publisher(make_sender(lambda: self._client))
        self._state: MonitorState | None = None

    @property
    def state(self) -> MonitorState | None:
        return self._state

    def start(self) -> None:
        self._publisher.start()

    def note_wake(self) -> None:
        self._monitor.note_wake()

    # -- periodic work -------------------------------------------------------------

    def tick(self) -> MonitorState | None:
        """Read new Teams log lines and publish when needed; ``None`` if the tick failed."""
        try:
            state = self._monitor.tick()
        except Exception:  # never let the timer die
            log.exception("presence tick failed")
            return None
        if state.changed:
            log.info(
                "presence %s (teams=%s, source=%s)",
                state.presence.ha_state,
                state.raw,
                state.source.value,
            )
        self._state = state
        if self._client is not None and (state.changed or self._publisher.heartbeat_due()):
            self._publisher.submit(build_payload(state.presence, state.raw, state.since))
        return state

    def status_text(self) -> str:
        state = self._state
        if state is None:
            return "Stato: …"
        label = state.presence.label
        if state.presence is Presence.UNKNOWN and state.raw:
            label = f"{label} ({state.raw})"
        text = f"Stato: {label} (dalle {state.since.astimezone():%H:%M})"
        note = _SOURCE_NOTES.get(state.source)
        return f"{text} — {note}" if note else text

    def ha_text(self) -> str:
        if self._client is None:
            return "Home Assistant: non configurato"
        result = self._publisher.last_result
        if result is None:
            return "Home Assistant: in attesa…"
        at = datetime.fromtimestamp(result.at).strftime("%H:%M")
        if result.ok:
            return f"Home Assistant: ✓ inviato alle {at}"
        return f"Home Assistant: ✗ {describe_error(result.error)} ({at})"

    # -- configuration -------------------------------------------------------------

    def _build_client(self) -> HomeAssistantClient | None:
        token = load_token()
        if (
            token
            and is_valid_ha_url(self._config.ha_url)
            and is_valid_entity_id(self._config.entity_id)
        ):
            return HomeAssistantClient(self._config.ha_url, token, self._config.entity_id)
        return None

    def _apply_settings(self) -> None:
        self._store.save(self._config)
        self._client = self._build_client()
        self.send_now()

    def edit_url(self) -> None:
        value = self._dialogs.ask(
            "URL Home Assistant", "Es. http://homeassistant.local:8123", self._config.ha_url
        )
        if value is None:
            return
        if not is_valid_ha_url(value):
            self._dialogs.alert(
                "URL non valido", "Usa un indirizzo http:// o https:// senza percorso."
            )
            return
        self._config.ha_url = normalize_ha_url(value)
        self._apply_settings()

    def edit_token(self) -> None:
        value = self._dialogs.ask(
            "Token Home Assistant",
            "Long-lived access token (Profilo › Sicurezza). Lascia vuoto per non modificarlo.",
            "",
            secure=True,
        )
        if not value:
            return
        if not is_valid_token(value):
            self._dialogs.alert("Token non valido", "Incolla il token senza spazi né a capo.")
            return
        save_token(value)
        self._apply_settings()

    def edit_entity_id(self) -> None:
        value = self._dialogs.ask("Entity ID", "Es. sensor.teams_status", self._config.entity_id)
        if value is None:
            return
        if not is_valid_entity_id(value):
            self._dialogs.alert("Entity ID non valido", "Usa il formato sensor.nome_in_minuscolo.")
            return
        self._config.entity_id = value
        self._apply_settings()

    def check_connection(self) -> None:
        if self._client is None:
            self._dialogs.alert("Home Assistant", "Configura URL, token ed entity ID.")
            return
        try:
            self._client.check()
        except HAError as exc:
            self._dialogs.alert("Connessione non riuscita", describe_error(exc))
            return
        self._dialogs.alert("Connessione riuscita", "Home Assistant risponde: API running.")

    # -- actions -------------------------------------------------------------------

    def send_now(self) -> None:
        state = self._state
        if state is not None and self._client is not None:
            self._publisher.submit(build_payload(state.presence, state.raw, state.since))

    def startup_enabled(self) -> bool:
        return self._startup.is_installed()

    def toggle_startup(self) -> bool:
        """Flip start-at-login; return whether it is now enabled."""
        try:
            if self._startup.is_installed():
                self._startup.uninstall()
            else:
                self._startup.install()
        except OSError as exc:
            log.exception("start-at-login update failed")
            self._dialogs.alert("Avvio al login", f"Operazione non riuscita: {exc}")
        return self._startup.is_installed()

    def shutdown(self) -> None:
        """Stop publishing, with one last attempt to set the sensor to ``unknown``."""
        log.info("quitting")
        final = None
        if self._client is not None:
            final = build_payload(Presence.UNKNOWN, None, datetime.now().astimezone())
        self._publisher.stop(final)
