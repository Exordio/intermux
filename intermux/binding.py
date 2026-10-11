"""Binding an app to an interface: the flow shared by the CLI and the GUI."""

from __future__ import annotations

from enum import Enum
from typing import Callable

from intermux.apps import launcher, processes
from intermux.net import interfaces, namespace
from intermux.net.namespace import Namespace
from intermux.system.users import User


class OnRunning(Enum):
    RESTART = "restart"
    SEPARATE = "separate"
    CANCEL = "cancel"


class BindError(Exception):
    pass


def bind(app: str, iface_name: str, user: User,
         on_running: Callable[[str, list[int]], OnRunning]) -> Namespace | None:
    """Start the app through the interface. Returns None if the user cancelled.

    on_running is asked what to do when the app is already open: restart it on
    the selected network, start a second instance with a separate profile, or cancel.
    """
    path = launcher.resolve(app)
    if path is None:
        raise BindError(f"Application not found: {app}")
    reason = launcher.unsupported_reason(path)
    if reason:
        raise BindError(reason)
    iface = interfaces.find(iface_name)
    if iface is None or not iface.up:
        raise BindError(f"Interface {iface_name} is not up")

    choice = None
    pids = processes.running(path, user.uid)
    if pids:
        choice = on_running(path, pids)
        if choice is OnRunning.CANCEL:
            return None
        if choice is OnRunning.RESTART:
            processes.stop(pids)

    ns = namespace.setup(iface)
    launcher.launch(path, ns, iface.name, user, separate_profile=choice is OnRunning.SEPARATE)
    return ns
