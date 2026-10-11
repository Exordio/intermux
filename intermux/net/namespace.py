"""One network namespace per interface, wired to the host with a veth pair, NAT and policy routing."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shlex
import shutil
from dataclasses import dataclass, field
from typing import Callable

from intermux.apps import processes
from intermux.net import dns, interfaces, registry, traffic
from intermux.net.interfaces import Interface
from intermux.system.shell import IP, IPTABLES, SYSCTL, run

log = logging.getLogger(__name__)

NETNS_ETC = "/etc/netns"
TABLE_BASE = 200
PRIORITY_BASE = 500
FALLBACK_METRIC = "4096"

CONNECTED = "connected"
NO_ROUTE = "no route"
INTERFACE_DOWN = "interface down"
INTERFACE_MISSING = "interface missing"

_NAME = re.compile(r"^ns_([0-9a-f]{8})$")
_POLICY_RULE = re.compile(r"^(\d+):\s+from 10\.0\.(\d+)\.0/24 .*lookup (\d+)")
_LEGACY_RT_TABLES = ("/etc/iproute2/rt_tables", "/usr/share/iproute2/rt_tables")


@dataclass(frozen=True)
class Namespace:
    """All names and numbers derive from the interface name, so they are stable across runs."""

    key: str

    @classmethod
    def for_interface(cls, iface: str) -> Namespace:
        return cls(hashlib.md5(iface.encode()).hexdigest()[:8])

    @classmethod
    def from_name(cls, name: str) -> Namespace:
        return cls(name.removeprefix("ns_"))

    @property
    def name(self) -> str:
        return f"ns_{self.key}"

    @property
    def host_veth(self) -> str:
        return f"veth0_{self.key}"

    @property
    def ns_veth(self) -> str:
        return f"veth1_{self.key}"

    @property
    def octet(self) -> int:
        return int(self.key, 16) % 253 + 1

    @property
    def subnet(self) -> str:
        return f"10.0.{self.octet}.0/24"

    @property
    def host_ip(self) -> str:
        return f"10.0.{self.octet}.1"

    @property
    def ns_ip(self) -> str:
        return f"10.0.{self.octet}.2"

    @property
    def table(self) -> str:
        return str(TABLE_BASE + self.octet)

    @property
    def priority(self) -> str:
        return str(PRIORITY_BASE + self.octet)

    @property
    def etc_dir(self) -> str:
        return os.path.join(NETNS_ETC, self.name)

    @property
    def comment(self) -> str:
        return f"intermux:{self.name}"


@dataclass
class State:
    entry: registry.Entry
    connection: str
    running: dict[str, list[int]] = field(default_factory=dict)
    """App path -> pids of its main processes."""
    traffic: traffic.Counters | None = None

    @property
    def ns(self) -> Namespace:
        return Namespace.from_name(self.entry.namespace)


def existing() -> list[Namespace]:
    names = (line.split()[0] for line in run(IP, "netns", "list", check=False).splitlines() if line.strip())
    return [Namespace(match.group(1)) for match in map(_NAME.match, names) if match]


def setup(iface: Interface, dns_servers: list[str] | None = None) -> Namespace:
    """Create the namespace for the interface, or rewire it if it already exists.

    Reusing a live namespace keeps apps started in it earlier connected.
    dns_servers=None keeps the servers of a reused namespace and picks them
    automatically for a new one, see dns.auto_servers().
    """
    ns = Namespace.for_interface(iface.name)
    previous = registry.load(ns.name)
    if _is_alive(ns):
        log.info("Reusing %s for %s (%s)", ns.name, iface.name, ns.subnet)
        _unwire(ns)
    else:
        log.info("Creating %s for %s (%s)", ns.name, iface.name, ns.subnet)
        teardown(ns)
        _create(ns)
        previous = None

    route = _wire(ns, iface)
    if dns_servers is None and previous and not previous.dns_auto:
        dns_servers = previous.dns
    servers, auto = _apply_dns(ns, iface, dns_servers)
    registry.save(registry.Entry(
        namespace=ns.name, interface=iface.name, subnet=ns.subnet,
        route=" ".join(route) if route else "none",
        dns=servers, dns_auto=auto, apps=previous.apps if previous else [],
    ))
    return ns


def set_dns(ns: Namespace, dns_servers: list[str] | None) -> list[str]:
    """Change DNS of a live namespace. Apps already running in it pick the change up."""
    entry = registry.load(ns.name)
    iface = interfaces.find(entry.interface) if entry else None
    servers, auto = _apply_dns(ns, iface, dns_servers)
    if entry:
        entry.dns, entry.dns_auto = servers, auto
        registry.save(entry)
    return servers


def active() -> list[State]:
    """Live namespaces with their connection state and only the apps that still run in them."""
    all_interfaces = {iface.name: iface for iface in interfaces.all_interfaces()}
    result = []
    for ns in existing():
        entry = registry.load(ns.name) or registry.Entry(
            namespace=ns.name, interface=_guess_interface(ns, all_interfaces), subnet=ns.subnet, route="?",
            dns=dns.read_resolv_conf(ns.etc_dir), dns_auto=False,
        )
        names = processes.in_namespace(ns.name)
        running = {}
        for app in entry.apps:
            pids = [pid for pid, (name, _) in names.items() if name == processes.process_name(app.path)]
            if pids:
                running[app.path] = pids
        entry.apps = [app for app in entry.apps if app.path in running]
        connection = _connection(ns, all_interfaces.get(entry.interface))
        result.append(State(entry, connection, running, traffic.counters(ns.host_veth)))
    return result


def reconnect(ns: Namespace) -> bool:
    """Route the namespace through its interface again, e.g. after a VPN reconnect.

    Returns False if the interface is still not usable.
    """
    entry = registry.load(ns.name)
    iface = interfaces.find(entry.interface if entry else _guess_interface(ns, {}))
    if iface is None or not iface.up or _default_route(iface) is None:
        return False
    log.info("Reconnecting %s to %s", ns.name, iface.name)
    _unwire(ns)
    route = _wire(ns, iface)
    if entry:
        entry.route = " ".join(route) if route else "none"
        registry.save(entry)
    return True


def reconnect_lost(states: list[State] | None = None) -> list[str]:
    """Reconnect every namespace whose interface came back. Returns their names."""
    return [state.entry.namespace for state in (active() if states is None else states)
            if state.connection == NO_ROUTE and reconnect(state.ns)]


def teardown(ns: Namespace) -> None:
    _unwire(ns)
    run(IP, "netns", "del", ns.name, check=False)
    run(IP, "link", "del", ns.host_veth, check=False)
    shutil.rmtree(ns.etc_dir, ignore_errors=True)
    registry.remove(ns.name)


def reset() -> None:
    """Remove everything InterMux created, including leftovers of namespaces that no longer exist."""
    for ns in existing():
        teardown(ns)
    _delete_rules(lambda rule: "intermux:" in rule)
    for line in run(IP, "rule", "show", check=False).splitlines():
        match = _POLICY_RULE.match(line)
        if match:
            priority, octet, table = map(int, match.groups())
            if priority == PRIORITY_BASE + octet and table == TABLE_BASE + octet:
                run(IP, "rule", "del", "priority", str(priority), check=False)
                run(IP, "route", "flush", "table", str(table), check=False)
                _delete_rules(lambda rule: f"-s 10.0.{octet}.0/24" in rule and "MASQUERADE" in rule)
    _drop_legacy_rt_tables()


def _guess_interface(ns: Namespace, known: dict[str, Interface]) -> str:
    """For namespaces created before the registry existed."""
    names = known or {iface.name: iface for iface in interfaces.all_interfaces()}
    return next((name for name in names if Namespace.for_interface(name) == ns), "?")


def _connection(ns: Namespace, iface: Interface | None) -> str:
    if iface is None:
        return INTERFACE_MISSING
    if not iface.up:
        return INTERFACE_DOWN
    routes = run(IP, "route", "show", "table", ns.table, check=False).splitlines()
    return CONNECTED if any(not route.startswith("unreachable") for route in routes) else NO_ROUTE


def _is_alive(ns: Namespace) -> bool:
    return ns in existing() and bool(run(IP, "link", "show", ns.host_veth, check=False))


def _create(ns: Namespace) -> None:
    run(IP, "netns", "add", ns.name)
    run(IP, "link", "add", ns.host_veth, "type", "veth", "peer", "name", ns.ns_veth)
    run(IP, "link", "set", ns.ns_veth, "netns", ns.name)
    run(IP, "addr", "add", f"{ns.host_ip}/24", "dev", ns.host_veth)
    run(IP, "link", "set", ns.host_veth, "up")
    for args in (
        ("addr", "add", f"{ns.ns_ip}/24", "dev", ns.ns_veth),
        ("link", "set", ns.ns_veth, "up"),
        ("link", "set", "lo", "up"),
        ("route", "add", "default", "via", ns.host_ip),
    ):
        run(IP, "netns", "exec", ns.name, IP, *args)


def _wire(ns: Namespace, iface: Interface) -> list[str] | None:
    """NAT, forwarding and policy routing from the namespace to the interface."""
    run(SYSCTL, "-qw", "net.ipv4.ip_forward=1")
    _add_rule(ns, "nat", "POSTROUTING", "MASQUERADE", "-s", ns.subnet, "-o", iface.name)
    _add_rule(ns, "filter", "FORWARD", "ACCEPT", "-i", ns.host_veth, "-o", iface.name)
    _add_rule(ns, "filter", "FORWARD", "ACCEPT", "-i", iface.name, "-o", ns.host_veth,
              "-m", "conntrack", "--ctstate", "RELATED,ESTABLISHED")

    # Without its own table the namespace traffic would leave through the host's default route.
    # iif keeps the host's own replies to the namespace (source 10.0.N.1) in the main table.
    # The kernel drops routes of an interface that goes away (VPN disconnected, Wi-Fi lost);
    # the unreachable fallback keeps the lookup from falling through to the main table then.
    run(IP, "route", "add", "unreachable", "default", "metric", FALLBACK_METRIC, "table", ns.table)
    run(IP, "rule", "add", "from", ns.subnet, "iif", ns.host_veth, "table", ns.table, "priority", ns.priority)
    route = _default_route(iface)
    if route:
        run(IP, "route", "add", "default", *route, "table", ns.table)
        log.info("Routing %s %s (table %s)", ns.subnet, " ".join(route), ns.table)
    else:
        log.warning("%s has no gateway, %s has no network until it gets one", iface.name, ns.name)
    return route


def _unwire(ns: Namespace) -> None:
    run(IP, "rule", "del", "priority", ns.priority, check=False)
    run(IP, "route", "flush", "table", ns.table, check=False)
    # Older versions added MASQUERADE rules without a comment.
    _delete_rules(lambda rule: ns.comment in rule or (f"-s {ns.subnet}" in rule and "MASQUERADE" in rule))


def _apply_dns(ns: Namespace, iface: Interface | None, servers: list[str] | None) -> tuple[list[str], bool]:
    auto = not servers
    if auto:
        servers = dns.auto_servers(iface, interfaces.all_interfaces()) if iface else list(dns.FALLBACK)
    dns.write_resolv_conf(ns.etc_dir, servers)
    log.info("DNS for %s: %s%s", ns.name, ", ".join(servers), " (auto)" if auto else "")
    return servers, auto


def _default_route(iface: Interface) -> list[str] | None:
    if iface.gateways:
        return ["via", iface.gateways[0], "dev", iface.name]
    # Point-to-point links (tun, wg, ppp) have no next hop: the peer is the only way out.
    if iface.point_to_point:
        return ["dev", iface.name]
    return None


def _add_rule(ns: Namespace, table: str, chain: str, target: str, *matches: str) -> None:
    run(IPTABLES, "-t", table, "-I", chain, *matches,
        "-m", "comment", "--comment", ns.comment, "-j", target)


def _delete_rules(predicate: Callable[[str], bool]) -> None:
    for table in ("nat", "filter"):
        for rule in run(IPTABLES, "-t", table, "-S", check=False).splitlines():
            if rule.startswith("-A ") and predicate(rule):
                run(IPTABLES, "-t", table, "-D", *shlex.split(rule)[1:], check=False)


def _drop_legacy_rt_tables() -> None:
    """Older versions registered an <iface>_rt table per interface in rt_tables."""
    for path in _LEGACY_RT_TABLES:
        try:
            with open(path) as f:
                lines = f.read().splitlines()
        except OSError:
            continue
        kept = []
        for line in lines:
            parts = line.split()
            if len(parts) == 2 and parts[0].isdigit() and parts[1].endswith("_rt"):
                run(IP, "rule", "del", "table", parts[0], check=False)
                run(IP, "route", "flush", "table", parts[0], check=False)
            else:
                kept.append(line)
        if len(kept) != len(lines):
            try:
                with open(path, "w") as f:
                    f.write("\n".join(kept) + "\n")
            except OSError as exc:
                log.warning("Cannot clean up %s: %s", path, exc)
