"""Windows-specific helpers built on ctypes; kept out of the unit-tested core."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

assert sys.platform == "win32"

TEAMS_PROCESS = "ms-teams.exe"

_TH32CS_SNAPPROCESS = 0x00000002
_INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
_kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
_kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
_kernel32.Process32FirstW.restype = wintypes.BOOL
_kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
_kernel32.Process32NextW.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL


def is_process_running(image_name: str) -> bool:
    """Whether a process with this executable name (case-insensitive) is running."""
    snapshot = _kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if snapshot == _INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
        found = _kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        target = image_name.lower()
        while found:
            if entry.szExeFile.lower() == target:
                return True
            found = _kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        return False
    finally:
        _kernel32.CloseHandle(snapshot)


def is_teams_running() -> bool:
    return is_process_running(TEAMS_PROCESS)
