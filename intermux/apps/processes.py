from __future__ import annotations

import os
import signal
import time

from intermux.system.shell import run


def running(app: str, uid: int) -> list[int]:
    """PIDs of the user's processes named like the app. The kernel keeps only 15 characters of the name."""
    name = os.path.basename(app)[:15]
    return [int(pid) for pid in run("pgrep", "-x", "-u", str(uid), name, check=False).split()]


def stop(pids: list[int], timeout: float = 5.0) -> None:
    """SIGTERM, then SIGKILL for whatever is still alive after the timeout."""
    _send(pids, signal.SIGTERM)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and any(_alive(pid) for pid in pids):
        time.sleep(0.1)
    _send([pid for pid in pids if _alive(pid)], signal.SIGKILL)


def _send(pids: list[int], sig: int) -> None:
    for pid in pids:
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            pass


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True
