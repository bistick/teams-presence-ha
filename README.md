# Teams Presence

A macOS menu bar and Windows notification-area app that reads your Microsoft Teams presence from
the local Teams logs and publishes it to Home Assistant as a sensor. No Microsoft Graph access,
tenant permissions or cloud account are needed: everything runs on your computer and talks only to
your Home Assistant.

## How it works

- The app follows the newest `MSTeams_*.log` file of the new Teams client and extracts presence
  changes from it. The logs are in
  - macOS: `~/Library/Group Containers/UBF8T346G9.com.microsoft.teams/Library/Application Support/Logs`
  - Windows: `%LOCALAPPDATA%\Packages\MSTeams_8wekyb3d8bbwe\LocalCache\Microsoft\MSTeams\Logs`
- The current presence is shown in the menu bar (macOS, as an emoji) or in the notification area
  (Windows, as a colored dot), and sent to Home Assistant through the REST API
  (`POST /api/states/<entity_id>`).
- A change is sent immediately. The state is re-sent every 5 minutes as a heartbeat. Failed sends
  are retried with backoff.
- If Teams is not running, the presence is `offline`. If the log has not been written for more than
  12 minutes, the presence is `unknown`. Sleep time does not count towards the 12 minutes.
- When the app quits, or the user logs out or the computer shuts down, the app makes one last
  attempt to set the sensor to `unknown`.

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

- macOS 13 or later, or Windows 10/11, with the new Microsoft Teams client
- Python 3.12 or later
- A Home Assistant instance reachable from the computer, and a
  [long-lived access token](https://www.home-assistant.io/docs/authentication/#your-account-profile)

## Installation

### Run from source

macOS:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
teams-presence            # or: python -m teams_presence
```

Windows (PowerShell):

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e .
pythonw -m teams_presence   # pythonw: no console window
```

### Build the app

The same spec builds the app for the platform it runs on. PyInstaller does not cross-compile: build
the macOS app on a Mac and the Windows app on Windows.

```sh
pip install -e '.[app]'
pyinstaller --noconfirm packaging/TeamsPresence.spec
```

- **macOS**: the bundle is written to `dist/TeamsPresence.app`. Copy it to `/Applications` and open
  it. It runs only in the menu bar, without a Dock icon.
- **Windows**: the app is the single file `dist\TeamsPresence.exe`. Copy it anywhere (for example
  to `%LOCALAPPDATA%\Programs\TeamsPresence`) and run it. It runs only in the notification area;
  right-click the icon for the menu. It unpacks itself to a temporary folder at each start, so it
  takes a couple of seconds to appear.

The app icon comes from `packaging/assets/icon.png`; PyInstaller converts it to `.icns` or `.ico`.

The GitHub Actions workflow in `.github/workflows/build.yml` runs the tests and builds both apps on
every push, and uploads them as the `TeamsPresence-macos` and `TeamsPresence-windows` artifacts.

### Release

Pushing a `v*` tag publishes a GitHub release with both apps attached, built by the workflow. The
tag must match `version` in `pyproject.toml`, otherwise the release fails. The text at the top of
the release comes from `packaging/release-notes.md`, followed by notes generated from the commits.

```sh
git tag v0.1.0
git push origin v0.1.0
```

For a new version, update `version` in `pyproject.toml` and commit it before tagging.

## Configuration

Everything is configured from the app menu, under **Impostazioni** (Settings):

- **URL Home Assistant…**: the base URL, for example `http://homeassistant.local:8123`
- **Token…**: the long-lived access token, stored in the macOS Keychain or in the Windows
  Credential Manager
- **Entity ID…**: the sensor to publish, `sensor.teams_status` by default
- **Verifica connessione**: checks that the URL and the token work

Other menu items:

- **Invia ora**: sends the current state right away
- **Avvia al login**: starts the app at login, through a LaunchAgent on macOS or the `Run`
  registry key on Windows
- **Esci**: quits the app

The menu labels are in Italian.

On macOS, the first time it runs, the system may ask for permission to access the Teams data. If the menu reports
that access was denied, allow it under *System Settings › Privacy & Security*.

## Files

macOS:

| Path                                                     | Contents                          |
|----------------------------------------------------------|-----------------------------------|
| `~/Library/Application Support/TeamsPresence/config.json` | URL and entity ID                |
| macOS Keychain, service `TeamsPresence`                  | Home Assistant token              |
| `~/Library/Logs/TeamsPresence/`                          | App logs (`app.log`, rotated)     |
| `~/Library/LaunchAgents/it.denami.teams-presence.plist`  | Start-at-login agent, if enabled  |

Windows:

| Path                                                                  | Contents                         |
|-----------------------------------------------------------------------|----------------------------------|
| `%APPDATA%\TeamsPresence\config.json`                                 | URL and entity ID                |
| Windows Credential Manager, `TeamsPresence`                           | Home Assistant token             |
| `%LOCALAPPDATA%\TeamsPresence\Logs\`                                  | App logs (`app.log`, rotated)    |
| `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, value `TeamsPresence` | Start at login, if enabled |

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
- Only the new Teams client is supported, on macOS and Windows. Teams classic is not.
