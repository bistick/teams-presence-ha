"""rumps menu bar application (macOS) wiring the presence monitor to Home Assistant."""

from __future__ import annotations

import rumps

from teams_presence import macos
from teams_presence.config import ConfigStore
from teams_presence.controller import CONFIG_RESET_NOTICE, Controller, StartupItem
from teams_presence.presence import Presence


class RumpsDialogs:
    def ask(self, title: str, message: str, default: str, secure: bool = False) -> str | None:
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

    def alert(self, title: str, message: str) -> None:
        rumps.alert(title, message)


class TeamsPresenceApp(rumps.App):  # type: ignore[misc]
    def __init__(self, store: ConfigStore, startup: StartupItem) -> None:
        super().__init__("Teams Presence", title=Presence.UNKNOWN.emoji, quit_button=None)
        self._controller = Controller(store, startup, RumpsDialogs(), macos.is_teams_running)

        self._status_item = rumps.MenuItem("Stato: …")
        self._ha_item = rumps.MenuItem("Home Assistant: …")
        self._login_item = rumps.MenuItem("Avvia al login", callback=self._toggle_login)
        self._login_item.state = int(self._controller.startup_enabled())
        settings = rumps.MenuItem("Impostazioni")
        settings.add(rumps.MenuItem("URL Home Assistant…", callback=self._edit_url))
        settings.add(rumps.MenuItem("Token…", callback=self._edit_token))
        settings.add(rumps.MenuItem("Entity ID…", callback=self._edit_entity_id))
        settings.add(rumps.MenuItem("Verifica connessione", callback=self._check_connection))
        info: list[rumps.MenuItem] = [self._status_item, self._ha_item]
        if self._controller.config_reset:
            info.append(rumps.MenuItem(CONFIG_RESET_NOTICE))
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
        rumps.events.on_wake.register(self._controller.note_wake)
        self._controller.start()
        self._timer = rumps.Timer(self._tick, 1)
        self._timer.start()

    def _tick(self, _timer: rumps.Timer) -> None:
        state = self._controller.tick()
        if state is None:
            return
        self.title = state.presence.emoji
        self._status_item.title = self._controller.status_text()
        self._ha_item.title = self._controller.ha_text()

    def _edit_url(self, _sender: rumps.MenuItem) -> None:
        self._controller.edit_url()

    def _edit_token(self, _sender: rumps.MenuItem) -> None:
        self._controller.edit_token()

    def _edit_entity_id(self, _sender: rumps.MenuItem) -> None:
        self._controller.edit_entity_id()

    def _check_connection(self, _sender: rumps.MenuItem) -> None:
        self._controller.check_connection()

    def _send_now(self, _sender: rumps.MenuItem) -> None:
        self._controller.send_now()

    def _toggle_login(self, sender: rumps.MenuItem) -> None:
        sender.state = int(self._controller.toggle_startup())

    def _quit(self, _sender: rumps.MenuItem) -> None:
        rumps.quit_application()

    def _on_before_quit(self) -> None:
        self._timer.stop()
        self._controller.shutdown()
