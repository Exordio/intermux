from __future__ import annotations

import argparse
import os

from intermux import log
from intermux.binding import BindError, OnRunning, bind
from intermux.net import interfaces, namespace
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


def cmd_assign(args: argparse.Namespace) -> int:
    try:
        ns = bind(args.app, args.iface, invoking_user(), _ask_on_running)
    except (BindError, CommandError) as exc:
        print(f"Error: {exc}")
        return 1
    if ns is None:
        print("Cancelled.")
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
    commands.add_parser("reset", help="remove everything InterMux created").set_defaults(func=cmd_reset, root=True)
    assign = commands.add_parser("assign", help="start an application through an interface")
    assign.add_argument("--app", required=True, help="command name from PATH or path to the executable")
    assign.add_argument("--iface", required=True, help="network interface name")
    assign.set_defaults(func=cmd_assign, root=True)

    args = parser.parse_args(argv)
    if args.root and not is_root():
        parser.exit(1, f"'{args.command}' needs root, run it with sudo.\n")
    log.setup()
    return args.func(args)
