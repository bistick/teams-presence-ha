"""PyInstaller entry script: a bundle runs a file, not ``python -m teams_presence``."""

from teams_presence.__main__ import main

raise SystemExit(main())
