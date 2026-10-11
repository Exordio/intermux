from __future__ import annotations

import os
import signal
import time

from intermux.system.shell import IP, run


def process_names(app: str) -> set[str]:
    """Lowercased names the app's process may get: the kernel keeps 15 characters of the file name.

    Launchers often run a binary with another name or case (/usr/bin/discord starts
    .../Discord), so the target of a symlink counts as well.
    """
    return {os.path.basename(path)[:15].lower() for path in (app, os.path.realpath(app))}


def running(app: str, uid: int) -> list[int]:
    pids = set()
    for name in process_names(app):
        pids.update(int(pid) for pid in run("pgrep", "-i", "-x", "-u", str(uid), name, check=False).split())
    return sorted(pids)


def app_pids(app: str, launcher_pid: int | None, processes: dict[int, tuple[str, int]]) -> list[int]:
    """Main processes of an app in the namespace.

    The app is the child of the sudo process InterMux started, whatever it calls
    itself. Without that pid (the app was started by an older version, or sudo has
    exited), processes named like the app are used, without their same-named children.
    """
    if launcher_pid in processes:
        return [pid for pid, (_, parent) in processes.items() if parent == launcher_pid]
    names = process_names(app)
    return [pid for pid, (name, parent) in processes.items()
            if name.lower() in names and processes.get(parent, ("",))[0].lower() not in names]


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
