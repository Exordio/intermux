from __future__ import annotations

import os
import signal
import time

from intermux.system.shell import IP, run


def process_name(app: str) -> str:
    """Name the kernel gives the app's process: the file name cut to 15 characters."""
    return os.path.basename(app)[:15]


def running(app: str, uid: int) -> list[int]:
    return [int(pid) for pid in run("pgrep", "-x", "-u", str(uid), process_name(app), check=False).split()]


def names_in_namespace(namespace: str) -> set[str]:
    names = set()
    for pid in run(IP, "netns", "pids", namespace, check=False).split():
        try:
            with open(f"/proc/{pid}/comm") as f:
                names.add(f.read().strip())
        except OSError:
            pass
    return names


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
