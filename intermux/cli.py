from __future__ import annotations

import argparse
import os

from intermux import log
from intermux import binding
from intermux.binding import BindError, OnRunning, bind
from intermux.net import dns, interfaces, namespace, shaping, traffic
from intermux.net.namespace import Namespace, State
from intermux.system import deps
from intermux.system.privileges import is_root
from intermux.system.shell import CommandError
from intermux.system.users import invoking_user


def cmd_list(args: argparse.Namespace) -> int:
    found = interfaces.selectable()
    if not found:
        print("No active interfaces with an IPv4 address.")
    for iface in found:
        print(iface.name)
        print(f"  Type:      {iface.kind}")
        print(f"  Addresses: {', '.join(iface.addresses)}")
        print(f"  Gateways:  {', '.join(iface.gateways) or '-'}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    states = namespace.active()
    if not states:
        print("No namespaces.")
    for state in states:
        entry = state.entry
        print(entry.namespace)
        print(f"  State:     {state.connection}")
        print(f"  Interface: {entry.interface}")
        print(f"  Subnet:    {entry.subnet}")
        print(f"  Route:     {entry.route}")
        print(f"  DNS:       {', '.join(entry.dns)}{' (auto)' if entry.dns_auto else ''}")
        if state.traffic:
            print(f"  Traffic:   down {traffic.format_bytes(state.traffic.down)}, "
                  f"up {traffic.format_bytes(state.traffic.up)}")
        if entry.limit_down or entry.limit_up:
            print(f"  Limit:     down {shaping.format_mbit(entry.limit_down)}, "
                  f"up {shaping.format_mbit(entry.limit_up)} Mbit/s")
        apps = (f"{os.path.basename(path)} (PID {', '.join(map(str, pids))})" for path, pids in state.running.items())
        print(f"  Apps:      {', '.join(apps) or '-'}")
    return 0


def cmd_assign(args: argparse.Namespace) -> int:
    try:
        ns = bind(args.app, args.iface, invoking_user(), _ask_on_running, _parse_dns(args.dns))
    except (BindError, CommandError, ValueError) as exc:
        print(f"Error: {exc}")
        return 1
    if ns is None:
        print("Cancelled.")
    return 0


def cmd_dns(args: argparse.Namespace) -> int:
    ns = Namespace.for_interface(args.iface)
    if ns not in namespace.existing():
        print(f"Error: no namespace for {args.iface}, start an app through it first.")
        return 1
    try:
        servers = namespace.set_dns(ns, _parse_dns(args.servers))
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1
    print(f"{ns.name}: {', '.join(servers)}")
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    matches = _find_app(args.app, args.iface)
    for state, path in matches:
        binding.stop_app(state, path, force=args.kill)
        print(f"Stopped {os.path.basename(path)} in {state.entry.namespace}")
    return 0 if matches else _not_running(args.app)


def cmd_restart(args: argparse.Namespace) -> int:
    matches = _find_app(args.app, args.iface)
    for state, path in matches:
        binding.restart_app(state, path, invoking_user())
        print(f"Restarted {os.path.basename(path)} in {state.entry.namespace}")
    return 0 if matches else _not_running(args.app)


def cmd_remove(args: argparse.Namespace) -> int:
    states = [state for state in namespace.active() if state.entry.interface == args.iface]
    for state in states:
        binding.remove_namespace(state)
        print(f"Removed {state.entry.namespace} with everything running in it")
    if not states:
        print(f"Error: no namespace for {args.iface}.")
    return 0 if states else 1


def cmd_limit(args: argparse.Namespace) -> int:
    ns = Namespace.for_interface(args.iface)
    if ns not in namespace.existing():
        print(f"Error: no namespace for {args.iface}, start an app through it first.")
        return 1
    namespace.set_limits(ns, args.down or None, args.up or None)
    print(f"{ns.name}: down {shaping.format_mbit(args.down)}, up {shaping.format_mbit(args.up)} Mbit/s")
    return 0


def cmd_reconnect(args: argparse.Namespace) -> int:
    reconnected = namespace.reconnect_lost()
    print(f"Reconnected: {', '.join(reconnected)}" if reconnected else "Nothing to reconnect.")
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    namespace.reset()
    print("All namespaces, routes and firewall rules created by InterMux were removed.")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    missing = deps.missing()
    if not missing:
        print("All dependencies are installed.")
        return 0
    print("Missing dependencies:")
    for tool, hint in missing:
        print(f"  {tool}: {hint}")
    return 1


def _find_app(name: str, iface: str | None) -> list[tuple[State, str]]:
    """Running apps matching a command name or path, optionally only on one interface."""
    return [(state, path) for state in namespace.active()
            if iface is None or state.entry.interface == iface
            for path in state.running if name in (path, os.path.basename(path))]


def _not_running(name: str) -> int:
    print(f"Error: {name} is not running in any namespace.")
    return 1


def _parse_dns(text: str | None) -> list[str] | None:
    return None if text is None or text.strip().lower() == "auto" else dns.parse(text)


def _ask_on_running(app: str, pids: list[int]) -> OnRunning:
    print(f"{os.path.basename(app)} is already running (PID {', '.join(map(str, pids))}).")
    print("  1) Close it and start again on the selected network (default profile)")
    print("  2) Start a second instance with a separate profile")
    print("  3) Cancel")
    choices = {"1": OnRunning.RESTART, "2": OnRunning.SEPARATE, "3": OnRunning.CANCEL}
    while True:
        answer = input("Choice [1/2/3]: ").strip()
        if answer in choices:
            return choices[answer]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="intermux", description="Run applications through a chosen network interface.")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("list", help="list interfaces that can be used").set_defaults(func=cmd_list, root=False)
    commands.add_parser("check", help="check system dependencies").set_defaults(func=cmd_check, root=False)
    commands.add_parser("status", help="show namespaces and what they serve").set_defaults(func=cmd_status, root=False)
    for name, func, help_text in (("stop", cmd_stop, "stop an application started by InterMux"),
                                  ("restart", cmd_restart, "restart an application in the same namespace")):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("app", help="command name or path, as shown by status")
        command.add_argument("--iface", help="only in the namespace of this interface")
        if name == "stop":
            command.add_argument("--kill", action="store_true", help="SIGKILL at once instead of SIGTERM")
        command.set_defaults(func=func, root=True)
    limit = commands.add_parser("limit", help="limit bandwidth of a namespace (no options remove the limits)")
    limit.add_argument("--iface", required=True, help="interface the namespace serves")
    limit.add_argument("--down", type=float, help="download limit, Mbit/s")
    limit.add_argument("--up", type=float, help="upload limit, Mbit/s")
    limit.set_defaults(func=cmd_limit, root=True)
    remove = commands.add_parser("remove", help="stop everything in a namespace and remove it")
    remove.add_argument("--iface", required=True, help="interface the namespace serves")
    remove.set_defaults(func=cmd_remove, root=True)
    commands.add_parser("reconnect", help="reconnect namespaces whose interface came back") \
        .set_defaults(func=cmd_reconnect, root=True)
    commands.add_parser("reset", help="remove everything InterMux created").set_defaults(func=cmd_reset, root=True)
    assign = commands.add_parser("assign", help="start an application through an interface")
    assign.add_argument("--app", required=True, help="command name from PATH or path to the executable")
    assign.add_argument("--iface", required=True, help="network interface name")
    assign.add_argument("--dns", help='DNS servers, e.g. "1.1.1.1,9.9.9.9" (default: auto)')
    assign.set_defaults(func=cmd_assign, root=True)
    dns_cmd = commands.add_parser("dns", help="change DNS servers of an existing namespace")
    dns_cmd.add_argument("--iface", required=True, help="interface the namespace was created for")
    dns_cmd.add_argument("servers", help='"auto" or servers, e.g. "1.1.1.1,9.9.9.9"')
    dns_cmd.set_defaults(func=cmd_dns, root=True)

    args = parser.parse_args(argv)
    if args.root and not is_root():
        parser.exit(1, f"'{args.command}' needs root, run it with sudo.\n")
    log.setup()
    return args.func(args)
