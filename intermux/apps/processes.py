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


def in_namespace(namespace: str) -> dict[int, tuple[str, int]]:
    """Processes of the namespace: pid -> (name, parent pid)."""
    result = {}
    for pid in map(int, run(IP, "netns", "pids", namespace, check=False).split()):
        try:
            with open(f"/proc/{pid}/stat") as f:
                stat = f.read()
        except OSError:
            continue
        # The name is in parentheses and may contain spaces; the parent pid follows the state field.
        name = stat[stat.index("(") + 1:stat.rindex(")")]
        parent = int(stat[stat.rindex(")") + 2:].split()[1])
        result[pid] = (name, parent)
    return result


def with_descendants(pids: list[int], processes: dict[int, tuple[str, int]]) -> list[int]:
    result = list(pids)
    for pid in result:
        result += [child for child, (_, parent) in processes.items() if parent == pid and child not in result]
    return result


def stop(pids: list[int], timeout: float = 5.0, force: bool = False) -> None:
    """SIGTERM, then SIGKILL for whatever is still alive after the timeout. force sends SIGKILL at once."""
    if not force:
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
