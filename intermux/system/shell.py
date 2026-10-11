from __future__ import annotations

import logging
import os
import shutil
import subprocess

log = logging.getLogger(__name__)

# Network tools live in sbin, which is missing from PATH of regular users on some distros.
_SEARCH_PATH = os.pathsep.join([os.environ.get("PATH", ""), "/usr/sbin", "/sbin"])


class CommandError(RuntimeError):
    pass


def which(*names: str) -> str | None:
    for name in names:
        path = shutil.which(name, path=_SEARCH_PATH)
        if path:
            return path
    return None


IP = which("ip") or "ip"
IPTABLES = which("iptables", "iptables-nft", "iptables-legacy") or "iptables"
SYSCTL = which("sysctl") or "sysctl"


def run(*args: str, check: bool = True, timeout: float | None = None) -> str:
    """Run a command without a shell and return its stdout.

    With check=False a failure is only logged, which is what teardown code wants
    when the object it removes may not exist.
    """
    log.debug("$ %s", " ".join(args))
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        if check:
            raise CommandError(f"{args[0]}: {exc}") from exc
        log.debug("%s: %s", args[0], exc)
        return ""

    if result.returncode != 0:
        message = f"{' '.join(args)}: {result.stderr.strip()}"
        if check:
            raise CommandError(message)
        log.debug(message)
    return result.stdout.strip()
