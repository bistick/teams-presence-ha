# Teams Presence

A macOS menu bar app that reads your Microsoft Teams presence from the local Teams logs and
publishes it to Home Assistant as a sensor. No Microsoft Graph access, tenant permissions or
cloud account are needed: everything runs on your Mac and talks only to your Home Assistant.

## How it works

- The app follows the newest `MSTeams_*.log` file of the new Teams client, in
  `~/Library/Group Containers/UBF8T346G9.com.microsoft.teams/Library/Application Support/Logs`,
  and extracts presence changes from it.
- The current presence is shown as an emoji in the menu bar and sent to Home Assistant through
  the REST API (`POST /api/states/<entity_id>`).
- A change is sent immediately. The state is re-sent every 5 minutes as a heartbeat. Failed sends
  are retried with backoff.
- If Teams is not running, the presence is `offline`. If the log has not been written for more than
  12 minutes, the presence is `unknown`. Sleep time does not count towards the 12 minutes.
- When the app quits, or the Mac logs out or shuts down, the app makes one last attempt to set the
  sensor to `unknown`.

### Sensor states

| State            | Teams presence  | Menu bar |
|------------------|-----------------|----------|
| `available`      | Available       | 🟢       |
| `busy`           | Busy            | 🔴       |
| `do_not_disturb` | Do not disturb  | ⛔       |
| `be_right_back`  | Be right back   | 🟡       |
| `away`           | Away            | 🟡       |
| `offline`        | Offline         | ⚫       |
| `unknown`        | Unknown         | ⚪       |

The sensor (default `sensor.teams_status`) also carries these attributes: `friendly_name`, `icon`,
`device_class: enum`, `options`, `teams_availability` (the raw Teams value), `last_change`,
`last_seen` and `source`.

## Requirements

- macOS 13 or later, with the new Microsoft Teams client
- Python 3.12 or later
- A Home Assistant instance reachable from the Mac, and a
  [long-lived access token](https://www.home-assistant.io/docs/authentication/#your-account-profile)

## Installation

### Run from source

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
teams-presence            # or: python -m teams_presence
```

### Build the `.app` bundle

```sh
pip install -e '.[app]'
pyinstaller --noconfirm packaging/TeamsPresence.spec
```

The bundle is written to `dist/TeamsPresence.app`. Copy it to `/Applications` and open it. It runs
only in the menu bar, without a Dock icon.

## Configuration

Everything is configured from the menu bar, under **Impostazioni** (Settings):

- **URL Home Assistant…**: the base URL, for example `http://homeassistant.local:8123`
- **Token…**: the long-lived access token, stored in the macOS Keychain
- **Entity ID…**: the sensor to publish, `sensor.teams_status` by default
- **Verifica connessione**: checks that the URL and the token work

Other menu items:

- **Invia ora**: sends the current state right away
- **Avvia al login**: starts the app at login, through a LaunchAgent
- **Esci**: quits the app

The menu labels are in Italian.

The first time it runs, macOS may ask for permission to access the Teams data. If the menu reports
that access was denied, allow it under *System Settings › Privacy & Security*.

## Files

| Path                                                     | Contents                          |
|----------------------------------------------------------|-----------------------------------|
| `~/Library/Application Support/TeamsPresence/config.json` | URL and entity ID                |
| macOS Keychain, service `TeamsPresence`                  | Home Assistant token              |
| `~/Library/Logs/TeamsPresence/`                          | App logs (`app.log`, rotated)     |
| `~/Library/LaunchAgents/it.denami.teams-presence.plist`  | Start-at-login agent, if enabled  |

Only one copy of the app runs at a time.

## Development

```sh
pip install -e '.[dev]'
pytest
ruff check .
mypy
```

## Limitations

- The presence is parsed from Teams' internal log format. A Teams update can change that format
  without notice and stop the detection.
- Only the new Teams client on macOS is supported.
