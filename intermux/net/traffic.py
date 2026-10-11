"""Traffic of a namespace, counted on the host end of its veth pair: everything it sends or receives passes there."""

from __future__ import annotations

import json
from dataclasses import dataclass

from intermux.system.shell import IP, run


@dataclass(frozen=True)
class Counters:
    down: int
    up: int


def counters(host_veth: str) -> Counters | None:
    links = json.loads(run(IP, "-s", "-j", "link", "show", host_veth, check=False) or "[]")
    if not links:
        return None
    stats = links[0]["stats64"]
    # The host end transmits what the namespace downloads and receives what it uploads.
    return Counters(down=stats["tx"]["bytes"], up=stats["rx"]["bytes"])


def format_bytes(count: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if count < 1024:
            return f"{count:.0f} {unit}" if unit == "B" else f"{count:.1f} {unit}"
        count /= 1024
    return f"{count:.1f} TB"
