from __future__ import annotations

import json
from dataclasses import dataclass, field

from intermux.system.shell import IP, run

# Bridges and container/VM links have no way out of the host; veth also covers InterMux's own pairs.
VIRTUAL_PREFIXES = ("veth", "br-", "docker", "virbr", "vmnet", "vboxnet")
VPN_PREFIXES = ("tun", "tap", "wg", "ppp")

_KINDS = (
    (("wl",), "Wi-Fi"),
    (("en", "eth"), "Ethernet"),
    (("usb",), "USB"),
    (("bnep", "bt"), "Bluetooth"),
    (VPN_PREFIXES, "VPN"),
    (VIRTUAL_PREFIXES, "Virtual"),
)


@dataclass
class Interface:
    name: str
    up: bool
    point_to_point: bool = False
    addresses: list[str] = field(default_factory=list)
    gateways: list[str] = field(default_factory=list)

    @property
    def kind(self) -> str:
        return next((kind for prefixes, kind in _KINDS if self.name.startswith(prefixes)), "Unknown")

    @property
    def ipv4(self) -> list[str]:
        return [address for address in self.addresses if ":" not in address]

    @property
    def selectable(self) -> bool:
        return self.up and bool(self.ipv4) and not self.name.startswith(VIRTUAL_PREFIXES)


def all_interfaces() -> list[Interface]:
    gateways = _gateways()
    result = []
    for link in json.loads(run(IP, "-j", "addr", "show") or "[]"):
        name = link["ifname"]
        if name == "lo":
            continue
        result.append(Interface(
            name=name,
            up="UP" in link.get("flags", []),
            point_to_point="POINTOPOINT" in link.get("flags", []),
            addresses=[f"{a['local']}/{a['prefixlen']}" for a in link.get("addr_info", [])],
            gateways=gateways.get(name, []),
        ))
    return result


def selectable() -> list[Interface]:
    return [iface for iface in all_interfaces() if iface.selectable]


def find(name: str) -> Interface | None:
    return next((iface for iface in all_interfaces() if iface.name == name), None)


def _gateways() -> dict[str, list[str]]:
    """IPv4 gateways per device from the main routing table, default routes first."""
    routes = json.loads(run(IP, "-j", "route", "show") or "[]")
    routes.sort(key=lambda route: route.get("dst") != "default")
    result: dict[str, list[str]] = {}
    for route in routes:
        gateway = route.get("gateway")
        if gateway and gateway not in result.setdefault(route["dev"], []):
            result[route["dev"]].append(gateway)
    return result
