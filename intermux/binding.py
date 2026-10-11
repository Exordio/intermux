"""Binding apps to interfaces and controlling them afterwards: the flows shared by the CLI and the GUI."""

from __future__ import annotations

from enum import Enum
from typing import Callable

from intermux.apps import launcher, processes
from intermux.net import interfaces, namespace, registry
from intermux.net.namespace import Namespace, State
from intermux.system.users import User


class OnRunning(Enum):
    RESTART = "restart"
    SEPARATE = "separate"
    CANCEL = "cancel"


class BindError(Exception):
    pass


def bind(app: str, iface_name: str, user: User,
         on_running: Callable[[str, list[int]], OnRunning],
         dns_servers: list[str] | None = None) -> Namespace | None:
    """Start the app through the interface. Returns None if the user cancelled.

    on_running is asked what to do when the app is already open: restart it on
    the selected network, start a second instance with a separate profile, or cancel.
    dns_servers=None keeps DNS of an existing namespace or picks it automatically.
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

    ns = namespace.setup(iface, dns_servers)
    app = registry.App(path, separate_profile=choice is OnRunning.SEPARATE)
    launcher.launch(path, ns, iface.name, user, separate_profile=app.separate_profile)
    registry.add_app(ns.name, app)
    return ns


def stop_app(state: State, path: str, force: bool = False) -> None:
    _terminate(state, state.running.get(path, []), force)
    registry.remove_app(state.entry.namespace, path)


def restart_app(state: State, path: str, user: User) -> None:
    """Stop the app and start it again in the same namespace with the same options."""
    app = next((app for app in state.entry.apps if app.path == path), registry.App(path))
    _terminate(state, state.running.get(path, []), force=False)
    launcher.launch(path, state.ns, state.entry.interface, user, separate_profile=app.separate_profile)


def stop_all(state: State, force: bool = False) -> None:
    """Stop every process in the namespace, including ones InterMux did not start itself."""
    processes_in_ns = processes.in_namespace(state.entry.namespace)
    top = [pid for pid, (_, parent) in processes_in_ns.items() if parent not in processes_in_ns]
    _terminate(state, top, force)
    for app in state.entry.apps:
        registry.remove_app(state.entry.namespace, app.path)


def remove_namespace(state: State) -> None:
    stop_all(state)
    namespace.teardown(state.ns)


def _terminate(state: State, pids: list[int], force: bool) -> None:
    """Stop the processes, then kill whatever they left behind in the namespace."""
    tree = processes.with_descendants(pids, processes.in_namespace(state.entry.namespace))
    processes.stop(pids, force=force)
    processes.stop(tree, force=True)
