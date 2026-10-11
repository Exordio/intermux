"""One network namespace per interface, wired to the host with a veth pair, NAT and policy routing."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shlex
import shutil
from dataclasses import dataclass
from typing import Callable

from intermux.net import dns
from intermux.net.interfaces import Interface
from intermux.system.shell import IP, IPTABLES, SYSCTL, run

log = logging.getLogger(__name__)

NETNS_ETC = "/etc/netns"
TABLE_BASE = 200
PRIORITY_BASE = 500

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


def existing() -> list[Namespace]:
    names = (line.split()[0] for line in run(IP, "netns", "list", check=False).splitlines() if line.strip())
    return [Namespace(match.group(1)) for match in map(_NAME.match, names) if match]


def setup(iface: Interface) -> Namespace:
    ns = Namespace.for_interface(iface.name)
    log.info("Setting up %s for %s (%s)", ns.name, iface.name, ns.subnet)
    teardown(ns)

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

    run(SYSCTL, "-qw", "net.ipv4.ip_forward=1")
    _add_rule(ns, "nat", "POSTROUTING", "MASQUERADE", "-s", ns.subnet, "-o", iface.name)
    _add_rule(ns, "filter", "FORWARD", "ACCEPT", "-i", ns.host_veth, "-o", iface.name)
    _add_rule(ns, "filter", "FORWARD", "ACCEPT", "-i", iface.name, "-o", ns.host_veth,
              "-m", "conntrack", "--ctstate", "RELATED,ESTABLISHED")

    # Without its own table the namespace traffic would leave through the host's default route.
    # iif keeps the host's own replies to the namespace (source 10.0.N.1) in the main table.
    route = _default_route(iface)
    if route:
        run(IP, "route", "add", "default", *route, "table", ns.table)
        run(IP, "rule", "add", "from", ns.subnet, "iif", ns.host_veth, "table", ns.table, "priority", ns.priority)
        log.info("Routing %s %s (table %s)", ns.subnet, " ".join(route), ns.table)
    else:
        log.warning("%s has no gateway, %s will use the host's default route", iface.name, ns.name)

    dns.write_resolv_conf(ns.etc_dir, dns.system_servers())
    return ns


def teardown(ns: Namespace) -> None:
    run(IP, "rule", "del", "priority", ns.priority, check=False)
    run(IP, "route", "flush", "table", ns.table, check=False)
    run(IP, "netns", "del", ns.name, check=False)
    run(IP, "link", "del", ns.host_veth, check=False)
    # Older versions added MASQUERADE rules without a comment.
    _delete_rules(lambda rule: ns.comment in rule or (f"-s {ns.subnet}" in rule and "MASQUERADE" in rule))
    shutil.rmtree(ns.etc_dir, ignore_errors=True)


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
