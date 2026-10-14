"""rumps menu bar application wiring the presence monitor to Home Assistant."""

from __future__ import annotations

import logging
from datetime import datetime

import rumps

from teams_presence import macos
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
from teams_presence.launch_agent import LaunchAgent
from teams_presence.log_tailer import DEFAULT_LOG_DIR, LogTailer
from teams_presence.monitor import MonitorState, PresenceMonitor, SourceStatus
from teams_presence.presence import Presence
from teams_presence.publisher import Publisher, build_payload, make_sender

log = logging.getLogger(__name__)

_SOURCE_NOTES = {
    SourceStatus.LOGS_MISSING: "log di Teams non trovati",
    SourceStatus.PERMISSION_DENIED: (
        "accesso ai log negato: Impostazioni di Sistema › Privacy e sicurezza"
    ),
    SourceStatus.TEAMS_NOT_RUNNING: "Teams non è in esecuzione",
    SourceStatus.STALE: "log di Teams fermo da oltre 12 minuti",
}


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


class TeamsPresenceApp(rumps.App):  # type: ignore[misc]
    def __init__(self, store: ConfigStore, launch_agent: LaunchAgent) -> None:
        super().__init__("Teams Presence", title=Presence.UNKNOWN.emoji, quit_button=None)
        self._store = store
        loaded = store.load()
        if loaded.reset:
            log.warning("invalid config moved to %s.bak; defaults loaded", store.path)
        self._config = loaded.config
        self._client = self._build_client()
        self._launch_agent = launch_agent
        self._monitor = PresenceMonitor(LogTailer(DEFAULT_LOG_DIR), macos.is_teams_running)
        self._publisher = Publisher(make_sender(lambda: self._client))
        self._state: MonitorState | None = None

        self._status_item = rumps.MenuItem("Stato: …")
        self._ha_item = rumps.MenuItem("Home Assistant: …")
        self._login_item = rumps.MenuItem("Avvia al login", callback=self._toggle_login)
        self._login_item.state = int(launch_agent.is_installed())
        settings = rumps.MenuItem("Impostazioni")
        settings.add(rumps.MenuItem("URL Home Assistant…", callback=self._edit_url))
        settings.add(rumps.MenuItem("Token…", callback=self._edit_token))
        settings.add(rumps.MenuItem("Entity ID…", callback=self._edit_entity_id))
        settings.add(rumps.MenuItem("Verifica connessione", callback=self._check_connection))
        info: list[rumps.MenuItem] = [self._status_item, self._ha_item]
        if loaded.reset:
            info.append(
                rumps.MenuItem("⚠️ Configurazione non valida: ripristinati i valori predefiniti")
            )
        self.menu = [
            *info,
            None,
            rumps.MenuItem("Invia ora", callback=self._send_now),
            settings,
            self._login_item,
            None,
            rumps.MenuItem("Esci", callback=self._quit),
        ]

        # before_quit fires from applicationWillTerminate: on "Esci", logout and shutdown.
        rumps.events.before_quit.register(self._on_before_quit)
        rumps.events.on_wake.register(self._monitor.note_wake)
        self._publisher.start()
        self._timer = rumps.Timer(self._tick, 1)
        self._timer.start()

    # -- periodic work -------------------------------------------------------------

    def _tick(self, _timer: rumps.Timer) -> None:
        try:
            state = self._monitor.tick()
        except Exception:  # never let the timer die
            log.exception("presence tick failed")
            return
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
        self._refresh(state)

    def _refresh(self, state: MonitorState) -> None:
        self.title = state.presence.emoji
        label = state.presence.label
        if state.presence is Presence.UNKNOWN and state.raw:
            label = f"{label} ({state.raw})"
        text = f"Stato: {label} (dalle {state.since.astimezone():%H:%M})"
        note = _SOURCE_NOTES.get(state.source)
        self._status_item.title = f"{text} — {note}" if note else text
        self._ha_item.title = self._ha_text()

    def _ha_text(self) -> str:
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
        self._send_now(None)

    def _ask(self, title: str, message: str, default: str, secure: bool = False) -> str | None:
        response = rumps.Window(
            message=message,
            title=title,
            default_text=default,
            ok="Salva",
            cancel="Annulla",
            dimensions=(320, 24),
            secure=secure,
        ).run()
        return str(response.text).strip() if response.clicked else None

    def _edit_url(self, _sender: rumps.MenuItem) -> None:
        value = self._ask(
            "URL Home Assistant", "Es. http://homeassistant.local:8123", self._config.ha_url
        )
        if value is None:
            return
        if not is_valid_ha_url(value):
            rumps.alert("URL non valido", "Usa un indirizzo http:// o https:// senza percorso.")
            return
        self._config.ha_url = normalize_ha_url(value)
        self._apply_settings()

    def _edit_token(self, _sender: rumps.MenuItem) -> None:
        value = self._ask(
            "Token Home Assistant",
            "Long-lived access token (Profilo › Sicurezza). Lascia vuoto per non modificarlo.",
            "",
            secure=True,
        )
        if not value:
            return
        if not is_valid_token(value):
            rumps.alert("Token non valido", "Incolla il token senza spazi né a capo.")
            return
        save_token(value)
        self._apply_settings()

    def _edit_entity_id(self, _sender: rumps.MenuItem) -> None:
        value = self._ask("Entity ID", "Es. sensor.teams_status", self._config.entity_id)
        if value is None:
            return
        if not is_valid_entity_id(value):
            rumps.alert("Entity ID non valido", "Usa il formato sensor.nome_in_minuscolo.")
            return
        self._config.entity_id = value
        self._apply_settings()

    def _check_connection(self, _sender: rumps.MenuItem) -> None:
        if self._client is None:
            rumps.alert("Home Assistant", "Configura URL, token ed entity ID.")
            return
        try:
            self._client.check()
        except HAError as exc:
            rumps.alert("Connessione non riuscita", describe_error(exc))
            return
        rumps.alert("Connessione riuscita", "Home Assistant risponde: API running.")

    # -- actions -------------------------------------------------------------------

    def _send_now(self, _sender: rumps.MenuItem | None) -> None:
        state = self._state
        if state is not None and self._client is not None:
            self._publisher.submit(build_payload(state.presence, state.raw, state.since))

    def _toggle_login(self, sender: rumps.MenuItem) -> None:
        try:
            if self._launch_agent.is_installed():
                self._launch_agent.uninstall()
            else:
                self._launch_agent.install()
        except OSError as exc:
            log.exception("LaunchAgent update failed")
            rumps.alert("Avvio al login", f"Operazione non riuscita: {exc}")
        sender.state = int(self._launch_agent.is_installed())

    def _quit(self, _sender: rumps.MenuItem) -> None:
        rumps.quit_application()

    def _on_before_quit(self) -> None:
        log.info("quitting")
        self._timer.stop()
        final = None
        if self._client is not None:
            final = build_payload(Presence.UNKNOWN, None, datetime.now().astimezone())
        self._publisher.stop(final)
