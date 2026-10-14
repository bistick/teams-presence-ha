"""macOS-specific helpers built on pyobjc; kept out of the unit-tested core."""

from __future__ import annotations

from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSRunningApplication,
)

TEAMS_BUNDLE_ID = "com.microsoft.teams2"


def is_teams_running() -> bool:
    apps = NSRunningApplication.runningApplicationsWithBundleIdentifier_(TEAMS_BUNDLE_ID)
    return len(apps) > 0


def use_accessory_activation_policy() -> None:
    """Menu bar only: no Dock icon, while dialogs can still take keyboard focus."""
    NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
