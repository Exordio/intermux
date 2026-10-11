from __future__ import annotations

import logging
import os
import shutil
import subprocess

from intermux.apps import firefox
from intermux.net.namespace import Namespace
from intermux.system.session import session_env
from intermux.system.shell import IP
from intermux.system.users import User

log = logging.getLogger(__name__)


def resolve(app: str) -> str | None:
    """Absolute path for a command name from PATH or a path to an executable file."""
    path = app if os.sep in app else shutil.which(app)
    if path and os.path.isfile(path):
        return os.path.abspath(path)
    return None


def unsupported_reason(app: str) -> str | None:
    if "chromium" in os.path.basename(app).lower():
        return "Chromium cannot run inside a network namespace because of its sandbox."
    return None


def launch(app: str, ns: Namespace, iface: str, user: User, separate_profile: bool = False) -> None:
    """Start the app inside the namespace, dropping root privileges to the invoking user."""
    env = session_env(user)

    # A private TMPDIR keeps apps in different namespaces from finding each other through IPC sockets.
    if os.path.isdir(user.runtime_dir):
        tmp = os.path.join(user.runtime_dir, f"intermux-{ns.name}")
        os.makedirs(tmp, exist_ok=True)
        os.chown(tmp, user.uid, user.gid)
        env.update(TMPDIR=tmp, TMP=tmp, TEMP=tmp)

    flags = firefox.launch_flags(user, iface, separate_profile) if firefox.is_firefox(app) else []
    command = [
        IP, "netns", "exec", ns.name,
        "sudo", "-u", user.name,
        "env", *(f"{key}={value}" for key, value in env.items()),
        app, *flags,
    ]
    log.debug("Launching: %s", " ".join(command))
    subprocess.Popen(command, stdin=subprocess.DEVNULL, start_new_session=True)
    log.info("Started %s as %s in %s via %s", os.path.basename(app), user.name, ns.name, iface)
