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
from ctypes import wintypes

PBI_RS = os.environ.get(
    "PBI_RS_DESKTOP",
    r"C:\Program Files\Microsoft Power BI Desktop RS\bin\PBIDesktop.exe")
# Windows-only: LOCALAPPDATA is absent on other platforms, so resolve lazily.
WS = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft",
                  "Power BI Desktop SSRS", "AnalysisServicesWorkspaces")


def _kill() -> None:
    for img in ("PBIDesktop.exe", "msmdsrv.exe"):
        subprocess.run(["taskkill", "/F", "/IM", img], capture_output=True)
    time.sleep(4)


def _dialog() -> bool:
    u = ctypes.windll.user32
    found = [False]

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _l):
        if not u.IsWindowVisible(h):
            return True
        n = u.GetWindowTextLengthW(h)
        if n:
            b = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(h, b, n + 1)
            if "wrong" in b.value.lower():
                found[0] = True
        return True

    u.EnumWindows(cb, 0)
    return found[0]


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
    _kill()
    before = set(glob.glob(os.path.join(WS, "*")))
    proc = subprocess.Popen([PBI_RS, pbix])
    ws, t0 = None, time.time()
    while time.time() - t0 < 40:
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