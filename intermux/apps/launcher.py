from __future__ import annotations

import logging
import os
import shutil
import subprocess

from intermux.apps import firefox
from intermux.net.namespace import Namespace
from intermux.system.session import session_env
from intermux.system.shell import IP
from intermux.system.users import User, give_to

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


def launch(app: str, ns: Namespace, iface: str, user: User, separate_profile: bool = False) -> int:
    """Start the app inside the namespace, dropping root privileges to the invoking user.

    Returns the pid of the sudo process (ip netns exec replaces itself with it); the app is its child.
    """
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
        # -i: exactly the session environment, without what sudo adds (SUDO_*, its PATH).
        "env", "-i", *(f"{key}={value}" for key, value in env.items()),
        app, *flags,
    ]
    log.debug("Launching: %s", " ".join(command))
    # The app must not write to InterMux's terminal: it goes away when InterMux exits, and apps
    # that do not expect EIO on stdout (Electron ones, for instance) crash on the next write.
    output_path = app_log_path(app, user)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as output:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                                   start_new_session=True)
    give_to(user, output_path)
    log.info("Started %s as %s in %s via %s, output in %s",
             os.path.basename(app), user.name, ns.name, iface, output_path)
    return process.pid


def app_log_path(app: str, user: User) -> str:
    return os.path.join(user.data_dir, "apps", f"{os.path.basename(app)}.log")
