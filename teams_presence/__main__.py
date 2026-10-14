"""Entry point: ``python -m teams_presence``."""

from __future__ import annotations

import logging
import signal
from logging.handlers import RotatingFileHandler
from pathlib import Path

import rumps

from teams_presence import macos
from teams_presence.app import TeamsPresenceApp
from teams_presence.config import ConfigStore, app_support_dir, logs_dir
from teams_presence.instance_lock import AlreadyRunningError, acquire_lock
from teams_presence.launch_agent import LaunchAgent, current_program, default_plist_path

log = logging.getLogger("teams_presence")


def configure_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_dir / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[file_handler, logging.StreamHandler()],
    )


def main() -> int:
    log_dir = logs_dir()
    configure_logging(log_dir)
    try:
        lock = acquire_lock(app_support_dir() / "app.lock")
    except AlreadyRunningError:
        # Exit 0: a non-zero code would make the LaunchAgent's KeepAlive restart us.
        log.info("another instance is already running; exiting")
        return 0
    macos.use_accessory_activation_policy()
    agent = LaunchAgent(default_plist_path(), current_program(), log_dir)
    try:
        if agent.refresh():
            log.info("start-at-login now launches %s", current_program()[0])
    except OSError:
        log.exception("LaunchAgent refresh failed")
    log.info("starting")
    # SIGTERM (kill, launchd stop) goes through the normal quit path so the final state is sent;
    # the handler runs on the next timer tick, when the interpreter regains control.
    signal.signal(signal.SIGTERM, lambda _signum, _frame: rumps.quit_application())
    TeamsPresenceApp(ConfigStore(app_support_dir()), agent).run()
    lock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
