"""pystray notification-area application (Windows) wiring the presence monitor to Home Assistant.

pystray runs the Win32 message loop on the main thread. Everything else, the 1 s tick
and the tkinter dialogs, runs on one worker thread that also executes the menu actions,
so the controller is only ever used from a single thread, as with rumps on macOS.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, simpledialog

import pystray
from PIL import Image, ImageDraw

from teams_presence import windows
from teams_presence.config import ConfigStore
from teams_presence.controller import CONFIG_RESET_NOTICE, Controller, StartupItem
from teams_presence.presence import Presence

log = logging.getLogger(__name__)

TICK_SECONDS = 1.0
_TOOLTIP_MAX = 127  # NOTIFYICONDATAW.szTip holds 128 characters

_WM_QUERYENDSESSION = 0x0011
_WM_ENDSESSION = 0x0016
_WM_POWERBROADCAST = 0x0218
_PBT_APMRESUMESUSPEND = 0x0007
_PBT_APMRESUMEAUTOMATIC = 0x0012

_COLORS = {
    Presence.AVAILABLE: "#6BB700",
    Presence.BUSY: "#C4314B",
    Presence.DO_NOT_DISTURB: "#C4314B",
    Presence.BE_RIGHT_BACK: "#FFAA44",
    Presence.AWAY: "#FFAA44",
    Presence.OFFLINE: "#8A8886",
    Presence.UNKNOWN: "#C8C6C4",
}


def presence_image(presence: Presence, size: int = 64) -> Image.Image:
    """A Teams-style presence dot for the notification area."""
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    color = _COLORS[presence]
    box = (size * 0.06, size * 0.06, size * 0.94, size * 0.94)
    if presence in (Presence.OFFLINE, Presence.UNKNOWN):
        draw.ellipse(box, outline=color, width=round(size * 0.14))
    else:
        draw.ellipse(box, fill=color)
    if presence is Presence.DO_NOT_DISTURB:
        bar = size * 0.08
        draw.rectangle((size * 0.26, size / 2 - bar, size * 0.74, size / 2 + bar), fill="white")
    return image


class TkDialogs:
    """Modal dialogs; call them from the worker thread only."""

    def _root(self) -> tk.Tk:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        return root

    def ask(self, title: str, message: str, default: str, secure: bool = False) -> str | None:
        root = self._root()
        try:
            value = simpledialog.askstring(
                title,
                message,
                initialvalue=default,
                show="•" if secure else None,
                parent=root,
            )
        finally:
            root.destroy()
        return value.strip() if value is not None else None

    def alert(self, title: str, message: str) -> None:
        root = self._root()
        try:
            messagebox.showinfo(title, message, parent=root)
        finally:
            root.destroy()


class TrayApp:
    def __init__(self, store: ConfigStore, startup: StartupItem) -> None:
        self._controller = Controller(store, startup, TkDialogs(), windows.is_teams_running)
        self._images = {presence: presence_image(presence) for presence in Presence}
        self._actions: queue.Queue[Callable[[], None]] = queue.Queue()
        self._stopping = threading.Event()
        self._status = "Stato: …"
        self._ha = "Home Assistant: …"
        self._presence: Presence | None = None
        self._login_enabled = self._controller.startup_enabled()

        info = [
            pystray.MenuItem(lambda _item: self._status, None, enabled=False),
            pystray.MenuItem(lambda _item: self._ha, None, enabled=False),
        ]
        if self._controller.config_reset:
            info.append(pystray.MenuItem(CONFIG_RESET_NOTICE, None, enabled=False))
        settings = pystray.Menu(
            pystray.MenuItem("URL Home Assistant…", self._post(self._controller.edit_url)),
            pystray.MenuItem("Token…", self._post(self._controller.edit_token)),
            pystray.MenuItem("Entity ID…", self._post(self._controller.edit_entity_id)),
            pystray.MenuItem("Verifica connessione", self._post(self._controller.check_connection)),
        )
        menu = pystray.Menu(
            *info,
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Invia ora", self._post(self._controller.send_now)),
            pystray.MenuItem("Impostazioni", settings),
            pystray.MenuItem(
                "Avvia al login",
                self._post(self._toggle_login),
                checked=lambda _item: self._login_enabled,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Esci", self._quit),
        )
        self._icon = pystray.Icon(
            "TeamsPresence", self._images[Presence.UNKNOWN], "Teams Presence", menu
        )
        self._hook_window_messages()

    def run(self) -> None:
        self._controller.start()
        worker = threading.Thread(target=self._work, name="ui-worker", daemon=True)
        worker.start()
        self._icon.run()  # returns after "Esci"
        self._stopping.set()
        worker.join(timeout=2 * TICK_SECONDS)
        self._controller.shutdown()

    # -- worker thread -------------------------------------------------------------

    def _post(self, action: Callable[[], None]) -> Callable[[], None]:
        return lambda: self._actions.put(action)

    def _work(self) -> None:
        next_tick = time.monotonic()
        while not self._stopping.is_set():
            try:
                action = self._actions.get(timeout=max(0.0, next_tick - time.monotonic()))
            except queue.Empty:
                action = None
            if action is not None:
                try:
                    action()
                except Exception:
                    log.exception("menu action failed")
            if time.monotonic() >= next_tick:
                self._tick()
                next_tick = time.monotonic() + TICK_SECONDS

    def _tick(self) -> None:
        state = self._controller.tick()
        if state is None:
            return
        if state.presence is not self._presence:
            self._presence = state.presence
            self._icon.icon = self._images[state.presence]
        status, ha = self._controller.status_text(), self._controller.ha_text()
        if (status, ha) != (self._status, self._ha):
            self._status, self._ha = status, ha
            self._icon.title = f"Teams Presence — {status}"[:_TOOLTIP_MAX]
            self._icon.update_menu()

    def _toggle_login(self) -> None:
        self._login_enabled = self._controller.toggle_startup()
        self._icon.update_menu()

    # -- tray thread ---------------------------------------------------------------

    def _quit(self) -> None:
        self._icon.stop()

    def _hook_window_messages(self) -> None:
        """Handle logoff, shutdown and resume, which pystray's hidden window receives."""
        handlers = getattr(self._icon, "_message_handlers", None)
        if not isinstance(handlers, dict):
            log.warning("pystray internals changed: no final state at logoff, no wake events")
            return
        handlers[_WM_QUERYENDSESSION] = lambda _wparam, _lparam: 1
        handlers[_WM_ENDSESSION] = self._on_end_session
        handlers[_WM_POWERBROADCAST] = self._on_power_broadcast

    def _on_end_session(self, ending: int, _lparam: int) -> int:
        if ending:
            # The process can be killed as soon as this returns: send the final state now.
            self._stopping.set()
            self._controller.shutdown()
        return 0

    def _on_power_broadcast(self, event: int, _lparam: int) -> int:
        if event in (_PBT_APMRESUMESUSPEND, _PBT_APMRESUMEAUTOMATIC):
            self._controller.note_wake()
        return 1
