"""Strict RS Desktop oracle: MODEL_LOADED only if the user model is BOTH
attached (non-empty table list) AND still present after a hold window, with no
crash dump and no error dialog. Otherwise CRASH / NOT_MODEL_LOADED.

Usage: python _oracle_strict.py <pbix> [hold_s]
"""

from __future__ import annotations

import ctypes
import glob
import os
import sqlite3
import subprocess
import sys
import time
from collections.abc import Callable
from ctypes import wintypes

# Desktop executable: prefer the RS build, fall back to the regular Desktop; can
# be pinned with PBI_RS_DESKTOP (mirrors engine._default_desktop).
_DESKTOP_SUBPATHS = (
    r"Microsoft Power BI Desktop RS\bin\PBIDesktop.exe",
    r"Microsoft Power BI Desktop\bin\PBIDesktop.exe",
)


def _default_desktop() -> str:
    env = os.environ.get("PBI_RS_DESKTOP")
    if env:
        return env
    for sub in _DESKTOP_SUBPATHS:
        exe = os.path.join(r"C:\Program Files", sub)
        if os.path.exists(exe):
            return exe
    return os.path.join(r"C:\Program Files", _DESKTOP_SUBPATHS[0])


# Windows-only: LOCALAPPDATA is absent on other platforms, so resolve lazily.
# The workspace root differs between the RS build and the regular Desktop; honor
# PBI_RS_WS_ROOT, else auto-detect the sibling that exists (mirrors engine).
_WS_DIRS = ("Power BI Desktop SSRS", "Power BI Desktop")


def _ws_root() -> str:
    env = os.environ.get("PBI_RS_WS_ROOT")
    if env:
        return env
    base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft")
    for name in _WS_DIRS:
        cand = os.path.join(base, name, "AnalysisServicesWorkspaces")
        if os.path.isdir(cand):
            return cand
    return os.path.join(base, _WS_DIRS[0], "AnalysisServicesWorkspaces")


PBI_RS = _default_desktop()
WS = _ws_root()


def _kill() -> None:
    for img in ("PBIDesktop.exe", "msmdsrv.exe"):
        subprocess.run(["taskkill", "/F", "/IM", img], capture_output=True)
    time.sleep(4)


class _User32:
    """Typed access to the `user32` calls the error-dialog probe needs.

    typeshed declares `windll`/`WINFUNCTYPE` only inside its `win32` platform
    branch, so a host-side type check cannot see them. `CDLL`/`CFUNCTYPE` are
    declared for every platform and are the same thing on 64-bit Windows (the
    only target of Desktop RS): one calling convention covers both variants.
    Every raw `ctypes` call is wrapped here, so the untyped FFI boundary stays
    inside this class.
    """

    _enum_proc = ctypes.CFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def __init__(self) -> None:
        self._dll = ctypes.CDLL("user32")

    def is_visible(self, hwnd: int) -> bool:
        return bool(self._dll.IsWindowVisible(hwnd))

    def text_length(self, hwnd: int) -> int:
        return int(self._dll.GetWindowTextLengthW(hwnd))

    def window_text(self, hwnd: int, size: int) -> str:
        buffer = ctypes.create_unicode_buffer(size)
        self._dll.GetWindowTextW(hwnd, buffer, size)
        return buffer.value

    def enum_windows(self, proc: Callable[[int, int], bool]) -> None:
        self._dll.EnumWindows(self._enum_proc(proc), 0)


def _dialog() -> bool:
    """True when a visible window whose title mentions "wrong" is open."""
    user32 = _User32()
    found = False

    def on_window(hwnd: int, _param: int) -> bool:
        nonlocal found
        if not user32.is_visible(hwnd):
            return True
        length = user32.text_length(hwnd)
        if length and "wrong" in user32.window_text(hwnd, length + 1).lower():
            found = True
        return True

    user32.enum_windows(on_window)
    return found


def _tables(ws: str) -> list[str]:
    for db in glob.glob(os.path.join(ws, "Data", "*.db")):
        meta = os.path.join(db, "metadata.sqlitedb")
        if os.path.exists(meta):
            try:
                con = sqlite3.connect(meta)
                names = [r[0] for r in con.execute("SELECT Name FROM 'Table'")]
                con.close()
                if names:
                    return names
            except Exception:  # noqa: BLE001
                pass
    return []


def run(pbix: str, hold: int = 45) -> str:
    # Workspace-detection window: a cold launch on an emulated ARM guest can take
    # well over a minute, so allow a generous, env-tunable ceiling.
    open_timeout = int(os.environ.get("PBI_RS_ORACLE_OPEN_TIMEOUT", "180"))
    _kill()
    before = set(glob.glob(os.path.join(WS, "*")))
    proc = subprocess.Popen([PBI_RS, pbix])
    ws, t0 = None, time.time()
    while time.time() - t0 < open_timeout:
        d = set(glob.glob(os.path.join(WS, "*"))) - before
        if d:
            ws = sorted(d)[0]
            break
        time.sleep(1)
    if ws is None:
        _kill()
        return "NOENGINE"
    # wait for attach
    attached = False
    deadline = time.time() + hold
    while time.time() < deadline:
        if glob.glob(os.path.join(ws, "Data", "Msmdsrv.SQLDmpr.*.mdmp")):
            _kill()
            return "CRASH"
        if not os.path.isdir(ws):
            _kill()
            return "CRASH"
        if _tables(ws):
            attached = True
            break
        time.sleep(2)
    if not attached:
        _kill()
        return "NOT_MODEL_LOADED"
    # hold: must remain attached, workspace alive, no dump/dialog
    for _ in range(6):
        time.sleep(3)
        if not os.path.isdir(ws):
            _kill()
            return "CRASH"
        if glob.glob(os.path.join(ws, "Data", "Msmdsrv.SQLDmpr.*.mdmp")):
            _kill()
            return "CRASH"
        if _dialog():
            _kill()
            return "UI_ERROR"
        if not _tables(ws):
            _kill()
            return "CRASH"
    plain = proc.poll()
    _kill()
    return "MODEL_LOADED" if plain is None else "CRASH"


def main() -> int:
    hold = int(sys.argv[2]) if len(sys.argv) > 2 else 45
    v = run(sys.argv[1], hold)
    print(f"RESULT [{v}] {os.path.basename(sys.argv[1])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
