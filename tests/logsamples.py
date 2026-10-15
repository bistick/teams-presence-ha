"""Synthetic Teams log lines in the real format. No content copied from real logs."""

TS = "2026-10-12T16:36:04.789253+02:00"
_THREAD = "0x00000001f8e0a1c0"


def user_action(value: str, ts: str = TS) -> str:
    return (
        f"{ts} {_THREAD} <INFO> native_modules::UserDataCrossCloudModule: Received Action: "
        f"UserPresenceAction: {{cloud_context: https://teams.microsoft.com, availability: {value}}}"
    )


def icon_update(value: str, ts: str = TS) -> str:
    return (
        f"{ts} {_THREAD} <INFO> AppMenuMac: UpdateIconPresenceSending presence update "
        f"to icon v2: {value}"
    )


def global_state(value: str, ts: str = TS) -> str:
    return (
        f"{ts} {_THREAD} <INFO> native_modules::UserDataCrossCloudModule: BroadcastGlobalState: "
        f"New Global State Event: UserDataGlobalState total number of users: 1 "
        f"{{ availability: {value}, unread_notification_count: 0 }}"
    )


def cloud_state(value: str, ts: str = TS) -> str:
    return (
        f"{ts} {_THREAD} <INFO> native_modules::UserDataCrossCloudModule: CloudStateChanged: "
        f"New Cloud State Event: UserDataCloudState total number of users: 1 "
        f"{{ availability: {value}, unread_notification_count: 0 }}"
    )


def noise(ts: str = TS) -> str:
    return (
        f"{ts} {_THREAD} <INFO> auth::AuthenticationService::AcquireToken: Start | "
        f"resource: https://presence.teams.microsoft.com/, silent: true"
    )


CALL_WINDOW = "0b6d2f4e-1c3a-4f5e-9a7b-2c8d1e0f3a4b"


def _window(window: str, tags: str = "") -> str:
    return f"Window: (windowNumber=6349; name={window}; tags={tags})"


def call_start(window: str = CALL_WINDOW, ts: str = TS) -> str:
    return f"{ts} {_THREAD} <INFO> {_window(window)} Setting close prompt from web: meeting"


def call_end(window: str = CALL_WINDOW, ts: str = TS) -> str:
    return f"{ts} {_THREAD} <INFO> {_window(window)} Resetting close prompt from web"


def window_destroyed(window: str = CALL_WINDOW, ts: str = TS) -> str:
    return (
        f"{ts} {_THREAD} <INFO> {_window(window)} WindowCloseActionDestroy, "
        f"letting the window destroy"
    )


def close_prompt(value: str, window: str = CALL_WINDOW, ts: str = TS) -> str:
    return f"{ts} {_THREAD} <INFO> {_window(window)} Setting close prompt from web: {value}"
