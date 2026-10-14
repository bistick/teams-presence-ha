## Downloads

- **macOS** (Apple Silicon, macOS 13 or later): `TeamsPresence-macos.zip`. Unzip it and move
  `TeamsPresence.app` to `/Applications`.
- **Windows** (10/11): `TeamsPresence-windows.zip`. Unzip it and put `TeamsPresence.exe` anywhere,
  for example in `%LOCALAPPDATA%\Programs\TeamsPresence`.

## The apps are not signed

- **macOS** blocks apps downloaded from the internet that are not notarized by Apple. On the first
  start, right-click `TeamsPresence.app` and choose **Open**, or remove the quarantine flag:
  `xattr -dr com.apple.quarantine /Applications/TeamsPresence.app`. macOS asks every time whether
  Teams Presence may access data from other apps (the Teams logs); to stop the question, give it
  Full Disk Access in System Settings › Privacy & Security.
- **Windows** SmartScreen may warn about an unrecognized app: choose **More info** › **Run anyway**.
